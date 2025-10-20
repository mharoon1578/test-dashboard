import streamlit as st
import pandas as pd
import numpy as np
import re
from io import StringIO, BytesIO
from typing import Dict, List, Any
# Import Plotly for visualizations
import plotly.express as px

# --- Page Configuration ---
st.set_page_config(page_title="KDP Ads & Royalty Dashboard", layout="wide")

# --- Custom Styling (FIXED: Dual-Theme Compatible Metric Box) ---
st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] {
    gap: 15px;
}
/* Updated Metric Box Style for Dual-Theme Visibility */
.stMetric {
    /* Removing explicit background-color lets Streamlit handle light/dark mode */
    /* by using the default app background or a transparent fill, 
       which has better contrast with text color */
    border: 1px solid rgba(150, 150, 150, 0.2); /* Subtle, theme-neutral border */
    border-radius: 10px;
    padding: 15px; /* Increased padding */
    box-shadow: 0px 4px 8px rgba(0,0,0,0.1); /* Clearer shadow */
    transition: all 0.3s ease-in-out;
}
.stMetric:hover {
    box-shadow: 0px 6px 12px rgba(0,0,0,0.15); /* Interactive hover effect */
}
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------
# CORE STRING CLEANING UTILITY (The Critical Fix)
# ----------------------------------------------------
def robust_clean_string(s: Any) -> str:
    """Aggressively cleans and standardizes strings for safe comparison (e.g., Marketplace names)."""
    if pd.isna(s): return ''
    s = str(s).strip()
    
    # 1. Replace all forms of non-breaking spaces (common cloud issue) with standard space
    s = re.sub(r'[\u200b\xa0\s]+', ' ', s)
    
    # 2. Strip leading/trailing whitespace again, convert to uppercase, and return
    return s.strip().upper()


# ----------------------------------------------------
# Core Data Processing and Metric Calculation Functions
# ----------------------------------------------------

def load_df(uploaded_file: Any, file_type: str, header_index: int) -> pd.DataFrame:
    """Attempt to load DataFrame with a specific header index, using fresh content."""
    try:
        # Always get fresh content for independent reads
        file_content = uploaded_file.getvalue() 
        
        if uploaded_file.name.endswith(('.xlsx', '.xls')):
             content_buffer = BytesIO(file_content)
             df = pd.read_excel(content_buffer, header=header_index)
        else: # For CSV
             content_buffer = StringIO(file_content.decode('utf-8', errors='ignore'))
             df = pd.read_csv(content_buffer, header=header_index, encoding='utf-8', on_bad_lines='skip')
        
        df.columns = df.columns.astype(str).str.strip()
        df.dropna(how='all', inplace=True)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def get_royalty_file_metadata(uploaded_file: Any) -> tuple[str | None, List[str]]:
    """
    Extracts date and marketplaces reliably using a single cached run.
    """
    file_content = uploaded_file.getvalue()
    date_str = None
    marketplaces = []
    
    # --- 1. Date Extraction (Targeted Fix for KDP CSV header) ---
    try:
        if uploaded_file.name.endswith('.csv'):
            first_line = StringIO(file_content.decode('utf-8', errors='ignore')).readline()
            if first_line.strip().lower().startswith('sales period'):
                parts = first_line.split(',')
                if len(parts) > 1:
                    date_str = parts[1].strip()
        elif uploaded_file.name.endswith(('.xlsx', '.xls')):
            df_temp_header = pd.read_excel(BytesIO(file_content), header=None, nrows=1)
            date_str = str(df_temp_header.iloc[0, 1]).strip()
            
    except Exception:
        date_str = None
        
    # --- 2. Marketplace Extraction ---
    try:
        df = load_df(uploaded_file, "Royalty", 1)
    except Exception:
        df = pd.DataFrame()
            
    if not df.empty:
        df.columns = df.columns.astype(str).str.strip()
        if 'Marketplace' in df.columns:
            raw_marketplaces = df['Marketplace'].astype(str).str.strip().unique().tolist()
            marketplaces = [m for m in raw_marketplaces if m and m != 'N/A']
            
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
        # Attempt 1: Skip first row (header=1) - Correct for KDP files
        df = load_df(uploaded_file, file_type, 1)
        if not df.empty and 'Title' in df.columns.astype(str).str.strip():
            df.columns = df.columns.astype(str).str.strip()
            if file_date:
                df['Report Date'] = file_date
            return df

        # Attempt 2: Use first row as header (header=0) - Fallback
        df = load_df(uploaded_file, file_type, 0)
        if not df.empty and 'Title' in df.columns.astype(str).str.strip():
            df.columns = df.columns.astype(str).str.strip()
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

    # Prepare selected marketplace for robust comparison
    selected_marketplace_cleaned = robust_clean_string(selected_marketplace)

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

        # --- Filter by the selected marketplace (FIXED: Robust string comparison using helper) ---
        if selected_marketplace != "All Marketplaces" and 'Marketplace' in df.columns:
             # Apply aggressive cleaning to the data column for comparison
             df['Marketplace_Cleaned'] = df['Marketplace'].apply(robust_clean_string)
             df = df[df['Marketplace_Cleaned'] == selected_marketplace_cleaned].copy()
             
             df.drop(columns=['Marketplace_Cleaned'], inplace=True, errors='ignore')
             
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
                df.loc[:, 'Raw Units Sold'] = pd.to_numeric(df[col], errors='coerce').fillna(0).apply(np.floor).astype(int)
                break
        
        if df['Raw Royalty/Earnings'].sum() > 0 or df['Raw Units Sold'].sum() > 0:
            all_royalties.append(df[['Title', 'Author', 'Raw Royalty/Earnings', 'Raw Units Sold']])

    if not all_royalties:
        st.error(f"Could not find valid royalty data for **{selected_month}** in **{selected_marketplace}**. Please ensure **'All Marketplaces'** is selected if this persists.")
        return pd.DataFrame(), pd.DataFrame()

    combined_df = pd.concat(all_royalties, ignore_index=True)

    merged_royalty_df = combined_df.groupby(['Title', 'Author'], as_index=False).agg(
        {'Raw Royalty/Earnings': 'sum', 'Raw Units Sold': 'sum'}
    ).rename(columns={'Raw Royalty/Earnings': 'Total Royalty', 'Raw Units Sold': 'Total Units Sold'})
    
    st.success(f"Merged **{files_processed}** Royalty files for **{selected_month}** in **{selected_marketplace}** into **{len(merged_royalty_df)}** Product Families.")
    return merged_royalty_df, combined_df


@st.cache_data
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
        stripped_col_lower = original_col.strip().lower() # Added robust lower case check
        
        if 'campaign' in stripped_col_lower and 'name' not in found_cols:
            found_cols['Campaign Name'] = original_col
        elif stripped_col_lower == 'spend':
            found_cols['Ad Spend'] = original_col
        elif stripped_col_lower == 'sales':
            found_cols['Ad Sales'] = original_col
        elif stripped_col_lower == 'orders':
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

try:
    if royalty_files:
        for file in royalty_files:
            date_found, marketplaces_found = get_royalty_file_metadata(file)
            if date_found:
                file_to_date_map[file.name] = date_found
                unique_dates.add(date_found)
            all_marketplaces.update(marketplaces_found)

except Exception:
    pass # Continue to use manual/fallbacks

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
    st.sidebar.warning("⚠️ Auto-detection failed. Please enter the month manually (e.g., 'September 2025').")
    selected_month = st.sidebar.text_input("4. Reporting Month (Manual)", value="September 2025") # Defaulted based on your files


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
    st.sidebar.warning("⚠️ Marketplaces not detected. Defaulting to 'All Marketplaces'.")
    marketplace_options = ["All Marketplaces", "Amazon.com", "Audible.com"]
    selected_marketplace = st.sidebar.selectbox(
        "5. Marketplace (Manual Fallback)", 
        marketplace_options,
        index=0
    )
# ----------------------------------------

if "mappings" not in st.session_state:
    st.session_state["mappings"] = {}

# ----------------------------------------------------
# Main Dashboard Logic
# ----------------------------------------------------

# Only proceed if all required data and selections are available
if royalty_files and ads_file and selected_month and selected_marketplace and selected_month not in ["Upload Files", ""]:
    
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
            total_royalty = metrics_df["Total Royalty"].sum()
            total_revenue = total_royalty + total_ad_sales
            total_units = metrics_df["Total Units Sold"].sum()
            
            overall_acos = (total_ad_spend / total_ad_sales * 100) if total_ad_sales > 0 else 0
            overall_tacos = (total_ad_spend / total_revenue * 100) if total_revenue > 0 else 0

            # Grouped Metric Display for better visibility
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Revenue (Royalty + Ad Sales)", f"${total_revenue:,.2f}")
                st.metric("Total Royalty", f"${total_royalty:,.2f}")

            with col2:
                st.metric("Overall ACOS", f"{overall_acos:.1f}%")
                st.metric("Overall TACOS", f"{overall_tacos:.1f}%")

            with col3:
                st.metric("Total Units Sold", f"{int(total_units):,}")
                st.metric("Total Ad Spend", f"${total_ad_spend:,.2f}")

            st.markdown("---")
            st.subheader("Product Visualizations")
            
            # --- Chart 1: Revenue Breakdown by Product ---
            revenue_by_product = metrics_df.groupby('Title')[['Total Royalty', 'Ad Sales']].sum().reset_index()
            revenue_by_product = revenue_by_product[revenue_by_product['Total Royalty'] + revenue_by_product['Ad Sales'] > 0]
            
            fig_revenue = px.bar(
                revenue_by_product,
                x='Title',
                y=['Total Royalty', 'Ad Sales'],
                title='Total Revenue Breakdown by Product (Royalty vs. Ad Sales)',
                labels={'value': 'Revenue ($)', 'variable': 'Revenue Type', 'Title': 'Product Title'},
                height=500
            )
            fig_revenue.update_layout(xaxis={'categoryorder':'total descending'}, legend_title_text='Revenue Source')
            st.plotly_chart(fig_revenue, use_container_width=True)

            # --- Chart 2: ACOS vs TACOS ---
            # Filter out products with zero revenue as ACOS/TACOS would be misleading (infinity or zero)
            metrics_chart_df = metrics_df[metrics_df['Total Revenue'] > 0].copy()
            metrics_chart_df['Label'] = metrics_chart_df['Title'] + ' (' + metrics_chart_df['TACOS %'].round(1).astype(str) + '%)'
            
            fig_efficiency = px.scatter(
                metrics_chart_df,
                x='ACOS %',
                y='TACOS %',
                size='Total Revenue', # Size dots by revenue for impact
                color='Title',
                hover_name='Title',
                text='Label',
                title='Product Efficiency: ACOS vs. TACOS',
                height=500
            )
            fig_efficiency.update_traces(textposition='top center')
            fig_efficiency.update_layout(showlegend=False)
            st.plotly_chart(fig_efficiency, use_container_width=True)


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
                        st.rerun()  # Updated to use the new method
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
        st.error("⚠️ **Dashboard cannot load.** Please check the following issues:")
        if not royalty_files or not ads_file:
            st.markdown("- **Upload Status:** Ensure both Royalty files (Step 2) and the Advertising file (Step 3) are uploaded.")
        if selected_month in ["Upload Files", ""]:
            st.markdown("- **Reporting Month:** If Step 4 is blank, use the **Manual Fallback** to enter the correct month (e.g., `September 2025`).")
        if royalty_df_merged.empty and royalty_files and selected_month not in ["Upload Files", ""]:
            st.markdown(f"- **Royalty Data Filtered:** Could not find valid royalty data for **{selected_month}** in **{selected_marketplace}**. The robust marketplace cleaning is now active. As a temporary workaround, **please select 'All Marketplaces' in Step 5**.")
        if ads_file and ads_df.empty:
            st.markdown("- **Advertising File:** Ensure your Ads file is a standard AdLabs export format (header row is correct). The column detection is now more robust against case and spacing.")
        
else:
    st.info("👆 Please upload all KDP Royalty files (Step 2) and the Advertising Data file (Step 3) to activate the dashboard.")
