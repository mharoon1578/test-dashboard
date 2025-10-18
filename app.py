import streamlit as st
import pandas as pd
import numpy as np
import re
from io import StringIO, BytesIO
from typing import Dict, List, Any

# --- Page Configuration ---
st.set_page_config(page_title="KDP Ads & Royalty Dashboard", layout="wide")

# --- Custom Styling ---
st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] {
    gap: 15px;
}
.stMetric {
    background-color: #f0f2f6;
    border-radius: 10px;
    padding: 10px;
    box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
}
</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------
# Core Data Processing and Metric Calculation Functions
# ----------------------------------------------------

def read_file_content(uploaded_file):
    """Helper to get file content and handle common formats."""
    file_content = uploaded_file.getvalue()
    if uploaded_file.name.endswith('.csv'):
        # Decode, ignoring bad characters, and return as text stream
        return StringIO(file_content.decode('utf-8', errors='ignore'))
    elif uploaded_file.name.endswith(('.xlsx', '.xls')):
        # Return as byte stream for pandas to handle Excel
        return BytesIO(file_content)
    return None

def load_df(uploaded_file: Any, file_type: str, header_index: int) -> pd.DataFrame:
    """Attempt to load DataFrame with a specific header index."""
    try:
        content = read_file_content(uploaded_file)
        
        if uploaded_file.name.endswith(('.xlsx', '.xls')):
             df = pd.read_excel(content, header=header_index)
        else: # For CSV
             df = pd.read_csv(content, header=header_index, encoding='utf-8', on_bad_lines='skip')
        
        # CRITICAL FIX: Ensure all column headers are strings and cleaned
        df.columns = df.columns.astype(str).str.strip()
        df.dropna(how='all', inplace=True)
        return df
    except Exception:
        return pd.DataFrame() # Return empty on any loading failure


@st.cache_data(show_spinner=False)
def get_royalty_file_metadata(uploaded_file: Any) -> tuple[str | None, List[str]]:
    """
    FIX: A single, cached function to extract all necessary metadata 
    (Date and Marketplaces) from the uploaded file content.
    """
    file_content = uploaded_file.getvalue()
    date_str = None
    marketplaces = []
    
    # --- 1. Date Extraction ---
    try:
        if uploaded_file.name.endswith('.csv'):
            first_line = StringIO(file_content.decode('utf-8', errors='ignore')).readline()
            if first_line.lower().startswith('sales period'):
                parts = first_line.split(',')
                if len(parts) > 1:
                    date_str = parts[1].strip()
        elif uploaded_file.name.endswith(('.xlsx', '.xls')):
            # Read first row for date (usually column 1, index 0)
            df_temp_header = pd.read_excel(BytesIO(file_content), header=None, nrows=1)
            date_str = str(df_temp_header.iloc[0, 1]).strip()
            
    except Exception:
        date_str = None
        
    # --- 2. Marketplace Extraction ---
    # Load the actual data to find unique marketplaces. Using BytesIO/StringIO 
    # here ensures we are not relying on the Streamlit file object's state.
    
    # Try header=1 (common for KDP reports)
    try:
        if uploaded_file.name.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(BytesIO(file_content), header=1)
        else:
            df = pd.read_csv(StringIO(file_content.decode('utf-8', errors='ignore')), header=1, encoding='utf-8', on_bad_lines='skip')
    except Exception:
        # Fallback to header=0
        try:
            if uploaded_file.name.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(BytesIO(file_content), header=0)
            else:
                df = pd.read_csv(StringIO(file_content.decode('utf-8', errors='ignore')), header=0, encoding='utf-8', on_bad_lines='skip')
        except Exception:
            df = pd.DataFrame() # Loading failed
            
    if not df.empty and 'Marketplace' in df.columns.astype(str):
        df.columns = df.columns.astype(str).str.strip()
        if 'Marketplace' in df.columns:
            marketplaces = df['Marketplace'].astype(str).str.strip().unique().tolist()
            marketplaces = [m for m in marketplaces if m and m != 'N/A']

    return date_str if date_str and date_str.lower() != 'nan' else None, marketplaces


@st.cache_data
def load_data_from_uploader(uploaded_file: Any, file_type: str, file_date: str | None = None) -> pd.DataFrame:
    """Reads files with robust, dynamic header checking and injects the reporting date."""
    
    df = pd.DataFrame()
    
    if file_type == "Ads":
        df = load_df(uploaded_file, file_type, 0)
        if not df.empty and any('Campaign' in col for col in df.columns):
            return df
        return pd.DataFrame()
        
    else: # Royalty Files
        # Attempt 1: Skip first row (header=1)
        df = load_df(uploaded_file, file_type, 1)
        if not df.empty and 'Title' in df.columns.astype(str).str.strip():
            df.columns = df.columns.astype(str).str.strip() # Re-apply cleaning
            if file_date:
                df['Report Date'] = file_date
            return df

        # Attempt 2: Use first row as header (header=0)
        df = load_df(uploaded_file, file_type, 0)
        if not df.empty and 'Title' in df.columns.astype(str).str.strip():
            df.columns = df.columns.astype(str).str.strip() # Re-apply cleaning
            if file_date:
                df['Report Date'] = file_date
            return df

        return pd.DataFrame()

@st.cache_data
def combine_and_merge_royalty_data(royalty_files: List[Any], file_to_date_map: Dict[str, str], selected_month: str, selected_marketplace: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Combines, standardizes, filters by date/marketplace, and merges all royalty files."""
    if not royalty_files or not selected_month:
        return pd.DataFrame(), pd.DataFrame()

    all_royalties = []
    files_processed = 0
    
    REVENUE_COLS = ['Royalty', 'Earnings']
    UNIT_COLS = ['Net Units Sold', 'Units Sold', 'Net Units Sold or Combined KENP', 'Kindle Edition Normalized Pages (KENP)']

    for file in royalty_files:
        file_date = file_to_date_map.get(file.name)
        df = load_data_from_uploader(file, "Royalty", file_date)
        
        if df.empty or 'Title' not in df.columns:
            continue
            
        # --- Filter by the selected month ---
        if 'Report Date' in df.columns:
            df = df[df['Report Date'] == selected_month].copy()
            if df.empty:
                continue

        # --- Filter by the selected marketplace ---
        if selected_marketplace != "All Marketplaces" and 'Marketplace' in df.columns:
             df['Marketplace'] = df['Marketplace'].astype(str).str.strip()
             df = df[df['Marketplace'] == selected_marketplace].copy()
             if df.empty:
                 continue

        files_processed += 1
        df['Author'] = df.get('Author', 'N/A')
        
        # --- Standardize Revenue Column ---
        df['Raw Royalty/Earnings'] = 0.0
        for col in REVENUE_COLS:
            if col in df.columns:
                df.loc[:, 'Raw Royalty/Earnings'] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                break
        
        # --- Standardize Units Column ---
        df['Raw Units Sold'] = 0
        for col in UNIT_COLS:
            if col in df.columns:
                # Use np.floor before converting to int to handle potential float/decimal results from parsing
                df.loc[:, 'Raw Units Sold'] = pd.to_numeric(df[col], errors='coerce').fillna(0).apply(np.floor).astype(int)
                break
        
        if df['Raw Royalty/Earnings'].sum() > 0 or df['Raw Units Sold'].sum() > 0:
            all_royalties.append(df[['Title', 'Author', 'Raw Royalty/Earnings', 'Raw Units Sold']])

    if not all_royalties:
        st.error(f"Could not find valid royalty data for **{selected_month}** in **{selected_marketplace}**.")
        return pd.DataFrame(), pd.DataFrame()

    combined_df = pd.concat(all_royalties, ignore_index=True)

    # 2. Product Family Consolidation
    merged_royalty_df = combined_df.groupby(['Title', 'Author'], as_index=False).agg(
        {'Raw Royalty/Earnings': 'sum', 'Raw Units Sold': 'sum'}
    ).rename(columns={'Raw Royalty/Earnings': 'Total Royalty', 'Raw Units Sold': 'Total Units Sold'})
    
    st.success(f"Merged **{files_processed}** Royalty files for **{selected_month}** in **{selected_marketplace}** into **{len(merged_royalty_df)}** Product Families.")
    return merged_royalty_df, combined_df


# (The rest of the helper functions: clean_ads_data, map_campaign, calculate_metrics are unchanged)

def clean_ads_data(ads_file: Any) -> pd.DataFrame:
    """Standardizes Advertising data columns based on AdLabs structure."""
    df = load_data_from_uploader(ads_file, "Ads")
    if df.empty:
        return pd.DataFrame()

    target_map = {
        'Campaign': 'Campaign Name',
        'Spend': 'Ad Spend',
        'Sales': 'Ad Sales',
        'Orders': 'Ad Units Sold',
    }
    
    found_cols = {}
    for original_col in df.columns:
        stripped_col = original_col.strip()
        
        if 'Campaign' in stripped_col and 'Name' not in found_cols:
            found_cols['Campaign Name'] = original_col
        elif stripped_col == 'Spend':
            found_cols['Ad Spend'] = original_col
        elif stripped_col == 'Sales':
            found_cols['Ad Sales'] = original_col
        elif stripped_col == 'Orders':
            found_cols['Ad Units Sold'] = original_col
            
    rename_dict = {orig: target for target, orig in found_cols.items()}
    df.rename(columns=rename_dict, inplace=True)
    
    expected_cols = list(target_map.values())
    missing_cols = [col for col in expected_cols if col not in df.columns]
    
    if missing_cols:
         st.error(f"Ads file still missing critical columns: {', '.join(missing_cols)}. Please check file format.")
         return pd.DataFrame()
    
    for col in expected_cols[1:]:
        df.loc[:, col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    return df


def map_campaign(name, mappings):
    """Applies campaign mappings (Rule -> Product)"""
    name = str(name)
    for rule, product in mappings.items():
        if re.search(rule, name, re.IGNORECASE):
            return product
    return "Unmapped"

@st.cache_data
def calculate_metrics(ads_df, royalties_df, mappings):
    """Merges ads and royalties data, applies mappings, and calculates ACOS/TACOS."""
    
    ads_df = ads_df.reset_index(drop=True) 
    
    ads_df["Mapped Product"] = ads_df["Campaign Name"].apply(
        lambda x: map_campaign(x, mappings)
    )
    
    ad_summary = ads_df.groupby("Mapped Product").agg({
        "Ad Spend": "sum",
        "Ad Sales": "sum",
        "Ad Units Sold": "sum",
        "Campaign Name": "count"
    }).reset_index().rename(columns={"Campaign Name": "Campaign Count"})
    
    merged = pd.merge(royalties_df, ad_summary, how="outer",
                      left_on="Title", right_on="Mapped Product")
    
    merged['Title'].fillna(merged['Mapped Product'], inplace=True)
    merged.drop(columns=['Mapped Product'], inplace=True, errors='ignore')
    
    cols_to_fill = ["Total Royalty", "Total Units Sold", "Ad Spend", "Ad Sales", "Ad Units Sold", "Campaign Count"]
    for col in cols_to_fill:
        if col in merged.columns:
            merged[col].fillna(0, inplace=True)
            
    merged["Total Revenue"] = merged["Total Royalty"] + merged["Ad Sales"]
    
    merged["ACOS %"] = np.where(
        merged["Ad Sales"] > 0,
        (merged["Ad Spend"] / merged["Ad Sales"]) * 100,
        0
    )
    
    merged["TACOS %"] = np.where(
        merged["Total Revenue"] > 0,
        (merged["Ad Spend"] / merged["Total Revenue"]) * 100,
        0
    )
    
    merged['Total Units Sold'] = merged['Total Units Sold'].astype(int)
    merged['Campaign Count'] = merged['Campaign Count'].astype(int)
    
    return merged

# ----------------------------------------------------
# Sidebar: Upload & Config
# ----------------------------------------------------
st.sidebar.header("Upload & Settings")

# 1. Account/Client (User-defined)
account = st.sidebar.selectbox("1. Account/Client", ["CuriousPress", "Client A", "Client B"])

royalty_files = st.sidebar.file_uploader(
    "2. Upload ALL KDP Royalty Files", 
    type=["csv", "xlsx"], 
    accept_multiple_files=True
)

ads_file = st.sidebar.file_uploader("3. Upload Advertising Data (AdLabs Export)", type=["csv", "xlsx"])

# --- Dynamic Date and Marketplace Extraction and Selection ---
file_to_date_map = {}
unique_dates = set()
all_marketplaces = set()

# CRITICAL FIX: Use try/except to catch silent failures during file processing
try:
    if royalty_files:
        for file in royalty_files:
            # Use the new cached function
            date_found, marketplaces_found = get_royalty_file_metadata(file)
            if date_found:
                file_to_date_map[file.name] = date_found
                unique_dates.add(date_found)
            all_marketplaces.update(marketplaces_found)

except Exception as e:
    st.sidebar.error(f"**CRITICAL ERROR:** Failed to process royalty files metadata. App is halted. Error: {e}")
    # Setting royalty_files to None ensures the dashboard doesn't attempt to run
    royalty_files = None
    ads_file = None


# 4. Reporting Month Selector
selected_month = None
if unique_dates:
    sorted_dates = sorted(list(unique_dates), reverse=True)
    selected_month = st.sidebar.selectbox(
        "4. Reporting Month", 
        sorted_dates, 
        index=0
    )
else:
    st.sidebar.text_input("4. Reporting Month (N/A)", value="Upload Files", disabled=True)

# 5. Marketplace Selector
selected_marketplace = None
if all_marketplaces:
    marketplace_options = ["All Marketplaces"] + sorted(list(all_marketplaces))
    selected_marketplace = st.sidebar.selectbox(
        "5. Marketplace", 
        marketplace_options, 
        index=0
    )
else:
    st.sidebar.text_input("5. Marketplace (N/A)", value="Upload Files", disabled=True)
# ----------------------------------------

if "mappings" not in st.session_state:
    st.session_state["mappings"] = {}

# ----------------------------------------------------
# Main Dashboard Logic
# ----------------------------------------------------

# Only proceed if all required data and selections are available
if royalty_files and ads_file and selected_month and selected_marketplace:
    
    royalty_df_merged, raw_royalty_combined = combine_and_merge_royalty_data(
        royalty_files, file_to_date_map, selected_month, selected_marketplace
    )
    
    ads_df = clean_ads_data(ads_file)
    
    if not royalty_df_merged.empty and not ads_df.empty and "Campaign Name" in ads_df.columns:
        
        metrics_df = calculate_metrics(ads_df, royalty_df_merged, st.session_state["mappings"])
        
        tab1, tab2, tab3 = st.tabs(["📊 Performance Summary", "📝 Campaign Mapping & Management", "📂 Data Feed / Raw Data"])

        with tab1:
            st.header(f"Performance Summary — {account} ({selected_marketplace}, {selected_month})")
            
            # Top-Level KPIs
            total_ad_spend = metrics_df["Ad Spend"].sum()
            total_ad_sales = metrics_df["Ad Sales"].sum()
            total_revenue = metrics_df["Total Royalty"].sum() + metrics_df["Ad Sales"].sum()
            total_units = metrics_df["Total Units Sold"].sum()
            
            overall_acos = (total_ad_spend / total_ad_sales * 100) if total_ad_sales > 0 else 0
            overall_tacos = (total_ad_spend / total_revenue * 100) if total_revenue > 0 else 0

            # Grouped Metric Display for better visibility
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Revenue", f"${total_revenue:,.2f}")
                st.metric("Total Ad Spend", f"${total_ad_spend:,.2f}")

            with col2:
                st.metric("Overall ACOS", f"{overall_acos:.1f}%")
                st.metric("Overall TACOS", f"{overall_tacos:.1f}%")

            with col3:
                st.metric("Total Units Sold", f"{int(total_units):,}")
                st.metric("Total Campaigns Mapped", f"{metrics_df['Campaign Count'].sum():,}")

            st.markdown("---")
            st.subheader("Product Performance Table (Consolidated)")
            
            display_cols = [
                "Title", "Author", "Total Revenue", "Total Royalty", "Ad Spend", 
                "Ad Sales", "Total Units Sold", "Campaign Count", "ACOS %", "TACOS %"
            ]
            st.dataframe(
                metrics_df[display_cols].sort_values(by="Total Revenue", ascending=False), 
                use_container_width=True
            )
            
            unmapped_spend = metrics_df[metrics_df['Title'] == 'Unmapped']['Ad Spend'].sum()
            if unmapped_spend > 0:
                st.warning(f"⚠️ **${unmapped_spend:,.2f}** in Ad Spend is currently **UNMAPPED**! Use the next tab to fix this.")

        with tab2:
            st.header("Campaign Mapping & Management (Self-Service)")

            with st.form("mapping_form"):
                st.subheader("Add New Mapping Rule")
                
                product_list = sorted(royalty_df_merged['Title'].unique())
                new_product = st.selectbox("Map To Product Title (Product Family)", product_list, key="map_select")
                
                new_rule = st.text_input("Mapping Keyword (e.g., 'book_title_keyword' found in campaign name)", key="map_rule")
                
                submitted = st.form_submit_button("Add Mapping Rule")

                if submitted:
                    if new_rule and new_product:
                        st.session_state["mappings"][new_rule.lower()] = new_product
                        st.success(f"Rule added: **'{new_rule}'** → **{new_product}**.")
                        st.experimental_rerun()
                    else:
                        st.warning("Please enter a keyword and select a product.")
            
            st.markdown("---")
            st.subheader("Unmapped Campaigns to Address")
            
            ads_df_temp = ads_df.copy()
            ads_df_temp["Mapped Product"] = ads_df_temp["Campaign Name"].apply(
                 lambda x: map_campaign(x, st.session_state["mappings"])
            )

            current_unmapped = ads_df_temp[ads_df_temp["Mapped Product"] == "Unmapped"]
            
            if current_unmapped.empty:
                st.success("✅ All campaigns are currently mapped (or have zero spend)! You are good to go.")
            else:
                st.info(f"You have **{len(current_unmapped['Campaign Name'].unique())}** unique unmapped campaigns (total spend: ${current_unmapped['Ad Spend'].sum():,.2f}).")
                unmapped_summary = current_unmapped.groupby('Campaign Name').agg(
                    {'Ad Spend': 'sum', 'Ad Sales': 'sum'}
                ).sort_values(by='Ad Spend', ascending=False).reset_index()
                
                st.dataframe(unmapped_summary, use_container_width=True)
                
            st.markdown("---")
            st.subheader("Current Mappings (Keyword → Product)")
            st.json(st.session_state["mappings"])

        with tab3:
            st.header("Data Feed / Raw Data View")

            st.markdown("---")
            st.subheader("Raw Advertising Data")
            st.dataframe(ads_df, use_container_width=True)
            
            st.markdown("---")
            st.subheader(f"Raw Combined Royalty Data (Filtered for {selected_marketplace}, {selected_month})")
            st.dataframe(raw_royalty_combined, use_container_width=True)


    else:
        # Secondary Error/Guidance check for flow failure
        st.error("⚠️ **Dashboard cannot load.** Please check the following issues:")
        if not royalty_files or not ads_file:
            st.markdown("- **Upload Status:** Ensure both Royalty files (Step 2) and the Advertising file (Step 3) are uploaded.")
        if royalty_files and not selected_month:
            st.markdown("- **Date Selection:** Ensure the **Reporting Month** (Step 4) selector is populated and selected after files upload.")
        if royalty_files and selected_month and royalty_df_merged.empty:
            st.markdown(f"- **Royalty Data Filtered:** Could not find valid royalty data for **{selected_month}** in **{selected_marketplace}**. Try selecting **All Marketplaces**.")
        if ads_file and ads_df.empty:
            st.markdown("- **Advertising File:** Ensure your Ads file is a standard AdLabs export format (header row is correct).")
        
else:
    st.info("👆 Please upload all KDP Royalty files (Step 2) and the Advertising Data file (Step 3) to activate the dashboard.")
