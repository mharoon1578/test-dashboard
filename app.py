import streamlit as st
import pandas as pd
import numpy as np
import re
from io import StringIO, BytesIO
from typing import Dict, List, Any

# --- Page Configuration ---
st.set_page_config(page_title="KDP Ads & Royalty Dashboard", layout="wide")

# --- Custom Styling (Optional but helpful for visibility) ---
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
        return StringIO(file_content.decode('utf-8', errors='ignore'))
    elif uploaded_file.name.endswith(('.xlsx', '.xls')):
        return BytesIO(file_content)
    return None

def load_df(uploaded_file, file_type, header_index):
    """Attempt to load DataFrame with a specific header index."""
    try:
        content = read_file_content(uploaded_file)
        # Note: We must reset the stream position if it's a stream, but since we are re-reading 
        # from the original uploaded_file.getvalue() inside read_file_content, this is fine.
        
        if uploaded_file.name.endswith(('.xlsx', '.xls')):
             # For Excel, rely on the header row being consistent relative to start of sheet
             df = pd.read_excel(content, header=header_index)
        else: # For CSV
             df = pd.read_csv(content, header=header_index, encoding='utf-8', on_bad_lines='skip')
        
        # CRITICAL FIX: Ensure all column headers are strings and cleaned
        df.columns = df.columns.astype(str).str.strip()
        df.dropna(how='all', inplace=True)
        return df
    except Exception:
        return pd.DataFrame() # Return empty on any loading failure

# --- NEW HELPER FUNCTION TO EXTRACT DATE ---
def extract_date_from_kdp_report(uploaded_file: Any) -> str | None:
    """Reads the first row of a KDP report to extract the month/year (e.g., 'September 2025')."""
    try:
        file_content = uploaded_file.getvalue()
        
        if uploaded_file.name.endswith('.csv'):
            # For CSV, the format is 'Sales Period,September 2025,...'
            # Read first line as text
            first_line = StringIO(file_content.decode('utf-8', errors='ignore')).readline()
            if first_line.lower().startswith('sales period'):
                parts = first_line.split(',')
                if len(parts) > 1:
                    date_str = parts[1].strip()
                    return date_str if date_str else None
            return None
            
        elif uploaded_file.name.endswith(('.xlsx', '.xls')):
            # For Excel, the date is usually in the second column of the first row (index 0, col 1)
            # Use BytesIO(file_content) to re-read the file
            df_temp = pd.read_excel(BytesIO(file_content), header=None, nrows=1)
            date_str = str(df_temp.iloc[0, 1]).strip()
            return date_str if date_str and date_str != 'nan' else None
        
        return None
    except Exception:
        return None
# --- END NEW HELPER FUNCTION ---


@st.cache_data
def load_data_from_uploader(uploaded_file: Any, file_type: str, file_date: str | None = None) -> pd.DataFrame:
    """Reads files with robust, dynamic header checking and injects the reporting date."""
    
    df = pd.DataFrame()
    
    # 1. Handle Ads File: Force header=0
    if file_type == "Ads":
        df = load_df(uploaded_file, file_type, 0)
        # Check if we found a column that contains 'Campaign'
        if not df.empty and any('Campaign' in col for col in df.columns):
            return df
        return pd.DataFrame()
        
    # 2. Handle Royalty Files: Try header=1, then fallback to header=0.
    else: 
        # Attempt 1: Skip first row (common for KDP reports)
        df = load_df(uploaded_file, file_type, 1)
        if not df.empty and 'Title' in df.columns:
            if file_date:
                df['Report Date'] = file_date
            return df

        # Attempt 2: Use first row as header (fallback for non-standard reports)
        df = load_df(uploaded_file, file_type, 0)
        if not df.empty and 'Title' in df.columns:
            if file_date:
                df['Report Date'] = file_date
            return df

        return pd.DataFrame()

@st.cache_data
def combine_and_merge_royalty_data(royalty_files: List[Any], file_to_date_map: Dict[str, str], selected_month: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Combines, standardizes, filters by date, and merges all royalty files."""
    if not royalty_files or not selected_month:
        return pd.DataFrame(), pd.DataFrame()

    all_royalties = []
    files_processed = 0
    
    # Define robust mappings for highly variable columns
    REVENUE_COLS = ['Royalty', 'Earnings']
    UNIT_COLS = ['Net Units Sold', 'Units Sold', 'Net Units Sold or Combined KENP', 'Kindle Edition Normalized Pages (KENP)']

    for file in royalty_files:
        # Get the date for this file to pass to the loader
        file_date = file_to_date_map.get(file.name)
        
        # Load the dataframe. The cached function uses file content hash and file_date as keys.
        df = load_data_from_uploader(file, "Royalty", file_date)
        
        # Check if the loaded DataFrame is valid
        if df.empty or 'Title' not in df.columns or (not any(col in df.columns for col in REVENUE_COLS) and not any(col in df.columns for col in UNIT_COLS)):
            continue
            
        # --- NEW: Filter by the selected month ---
        if 'Report Date' in df.columns:
            df = df[df['Report Date'] == selected_month].copy()
            if df.empty:
                continue # Skip if no data for the selected month

        files_processed += 1
        df['Author'] = df.get('Author', 'N/A')
        
        # --- Standardize Revenue Column ---
        df['Raw Royalty/Earnings'] = 0.0
        for col in REVENUE_COLS:
            if col in df.columns:
                # Coerce to numeric, handle errors, fill NA with 0
                # Use .loc to avoid SettingWithCopyWarning, especially after filtering
                df.loc[:, 'Raw Royalty/Earnings'] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                break
        
        # --- Standardize Units Column ---
        df['Raw Units Sold'] = 0
        for col in UNIT_COLS:
            if col in df.columns:
                # Coerce to numeric, handle errors, fill NA with 0, convert to int
                df.loc[:, 'Raw Units Sold'] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
                break
        
        # Only append if both Title and a numeric unit/revenue column were found
        if df['Raw Royalty/Earnings'].sum() > 0 or df['Raw Units Sold'].sum() > 0:
            all_royalties.append(df[['Title', 'Author', 'Raw Royalty/Earnings', 'Raw Units Sold']])

    if not all_royalties:
        st.error(f"Could not find valid royalty data for **{selected_month}** in any of the uploaded files.")
        return pd.DataFrame(), pd.DataFrame()

    combined_df = pd.concat(all_royalties, ignore_index=True)

    # 2. Product Family Consolidation (Merge Duplicates by Title + Author)
    merged_royalty_df = combined_df.groupby(['Title', 'Author'], as_index=False).agg(
        {'Raw Royalty/Earnings': 'sum', 'Raw Units Sold': 'sum'}
    ).rename(columns={'Raw Royalty/Earnings': 'Total Royalty', 'Raw Units Sold': 'Total Units Sold'})
    
    st.success(f"Merged **{files_processed}** Royalty files for **{selected_month}** into **{len(merged_royalty_df)}** Product Families.")
    return merged_royalty_df, combined_df # Return combined_df for Raw Data Tab


@st.cache_data
def clean_ads_data(ads_file: Any) -> pd.DataFrame:
    """Standardizes Advertising data columns based on AdLabs structure."""
    df = load_data_from_uploader(ads_file, "Ads")
    if df.empty:
        return pd.DataFrame()

    # Define the mapping from expected column names (stripped) in the source file
    # to the desired standard column names in the output DataFrame.
    target_map = {
        'Campaign': 'Campaign Name',
        'Spend': 'Ad Spend',
        'Sales': 'Ad Sales',
        'Orders': 'Ad Units Sold',
    }
    
    rename_dict = {}
    
    # Try to find the exact column names needed
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
            
    # Create rename dictionary from found columns
    rename_dict = {orig: target for target, orig in found_cols.items()}
    df.rename(columns=rename_dict, inplace=True)
    
    # 2. Final check for critical columns
    expected_cols = list(target_map.values())
    missing_cols = [col for col in expected_cols if col not in df.columns]
    
    if missing_cols:
         st.error(f"Ads file still missing critical columns: {', '.join(missing_cols)}. Please check file format.")
         return pd.DataFrame()
    
    # 3. Ensure necessary columns are numeric
    for col in expected_cols[1:]: # Ad Spend, Ad Sales, Ad Units Sold
        df.loc[:, col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    return df


def map_campaign(name, mappings):
    """Applies campaign mappings (Rule -> Product)"""
    # Ensure name is a string before applying regex
    name = str(name)
    for rule, product in mappings.items():
        if re.search(rule, name, re.IGNORECASE):
            return product
    return "Unmapped"

@st.cache_data
def calculate_metrics(ads_df, royalties_df, mappings):
    """Merges ads and royalties data, applies mappings, and calculates ACOS/TACOS."""
    
    # CRITICAL FIX: Ensure Ads Data has a unique, clean index
    ads_df = ads_df.reset_index(drop=True) 
    
    # 1. Apply Campaign Mapping to Ads Data 
    ads_df["Mapped Product"] = ads_df["Campaign Name"].apply(
        lambda x: map_campaign(x, mappings)
    )
    
    # 2. Aggregate Ads by Mapped Product
    ad_summary = ads_df.groupby("Mapped Product").agg({
        "Ad Spend": "sum",
        "Ad Sales": "sum",
        "Ad Units Sold": "sum",
        "Campaign Name": "count"
    }).reset_index().rename(columns={"Campaign Name": "Campaign Count"})
    
    # 3. Merge Royalty Data (Product Family) with Ad Summary
    merged = pd.merge(royalties_df, ad_summary, how="outer",
                      left_on="Title", right_on="Mapped Product")
    
    # 4. CRITICAL FIX: Populate the final product identifier (Title)
    merged['Title'].fillna(merged['Mapped Product'], inplace=True)
    merged.drop(columns=['Mapped Product'], inplace=True, errors='ignore')
    
    # Fill missing metrics values with 0
    cols_to_fill = ["Total Royalty", "Total Units Sold", "Ad Spend", "Ad Sales", "Ad Units Sold", "Campaign Count"]
    for col in cols_to_fill:
        if col in merged.columns:
            merged[col].fillna(0, inplace=True)
            
    
    # 5. Calculate Corrected Metrics
    
    # Total Revenue (Royalty + Ad Sales)
    merged["Total Revenue"] = merged["Total Royalty"] + merged["Ad Sales"]
    
    # ACOS %: Ad Spend / Ad Sales
    merged["ACOS %"] = np.where(
        merged["Ad Sales"] > 0,
        (merged["Ad Spend"] / merged["Ad Sales"]) * 100,
        0
    )
    
    # TACOS %: Ad Spend / Total Revenue (Royalty + Ad Sales)
    merged["TACOS %"] = np.where(
        merged["Total Revenue"] > 0,
        (merged["Ad Spend"] / merged["Total Revenue"]) * 100,
        0
    )
    
    # Final cleanup of columns to display
    merged['Total Units Sold'] = merged['Total Units Sold'].astype(int)
    merged['Campaign Count'] = merged['Campaign Count'].astype(int)
    
    return merged

# ----------------------------------------------------
# Sidebar: Upload & Config
# ----------------------------------------------------
st.sidebar.header("Upload & Settings")

# Multi-Account/Marketplace/Month Controls
account = st.sidebar.selectbox("1. Account/Client", ["CuriousPress", "Client A", "Client B"])
marketplace = st.sidebar.selectbox("2. Marketplace", ["US", "UK", "CA", "DE", "AU", "Other"])

# Multi-File Upload for Royalty Data
royalty_files = st.sidebar.file_uploader(
    "3. Upload ALL KDP Royalty Files", 
    type=["csv", "xlsx"], 
    accept_multiple_files=True
)

# Single File Upload for Ads Data
ads_file = st.sidebar.file_uploader("4. Upload Advertising Data (AdLabs Export)", type=["csv", "xlsx"])

# --- NEW: Date Extraction and Selection ---
file_to_date_map = {}
unique_dates = []

if royalty_files:
    for file in royalty_files:
        date_found = extract_date_from_kdp_report(file)
        if date_found:
            file_to_date_map[file.name] = date_found
    
    unique_dates = sorted(list(set(file_to_date_map.values())), reverse=True)

# Selectbox for the date
selected_month = None
if unique_dates:
    selected_month = st.sidebar.selectbox(
        "5. Reporting Month", 
        unique_dates, 
        index=0 # Default to the latest month
    )
else:
    st.sidebar.warning("Upload royalty files to select a month.")
    month_placeholder = st.sidebar.text_input("5. Reporting Month (N/A)", value="Upload Files", disabled=True)

# ----------------------------------------

# State: campaign mappings
if "mappings" not in st.session_state:
    st.session_state["mappings"] = {}

# ----------------------------------------------------
# Main Dashboard Logic
# ----------------------------------------------------

if royalty_files and ads_file and selected_month:
    # --- Load, Combine, and Clean Data ---
    
    # 1. Royalty Data Processing
    # Pass the file_to_date_map and the selected_month for filtering
    royalty_df_merged, raw_royalty_combined = combine_and_merge_royalty_data(royalty_files, file_to_date_map, selected_month)
    
    # 2. Ads Data Processing (Ads file is not date filtered here, assuming the uploaded file is for the selected period)
    ads_df = clean_ads_data(ads_file)
    
    if not royalty_df_merged.empty and not ads_df.empty and "Campaign Name" in ads_df.columns:
        # 3. Calculate Final Metrics
        metrics_df = calculate_metrics(ads_df, royalty_df_merged, st.session_state["mappings"])
        
        # --- Tabs ---
        tab1, tab2, tab3 = st.tabs(["📊 Performance Summary", "📝 Campaign Mapping & Management", "📂 Data Feed / Raw Data"])

        # ----------------------------------------------------
        # Tab 1: Performance Summary (Corrected Analytics)
        # ----------------------------------------------------
        with tab1:
            st.header(f"Performance Summary — {account} ({marketplace}, {selected_month})")
            
            # Top-Level KPIs
            total_ad_spend = metrics_df["Ad Spend"].sum()
            total_ad_sales = metrics_df["Ad Sales"].sum()
            total_royalty = metrics_df["Total Royalty"].sum()
            total_revenue = metrics_df["Total Royalty"].sum() + metrics_df["Ad Sales"].sum() # Recalculate if metrics_df is empty
            total_units = metrics_df["Total Units Sold"].sum()
            
            # Metric Calculation
            overall_acos = (total_ad_spend / total_ad_sales * 100) if total_ad_sales > 0 else 0
            overall_tacos = (total_ad_spend / total_revenue * 100) if total_revenue > 0 else 0

            # --- Fix for displaying metrics at different zoom levels ---
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
            # --- End Fix ---

            st.markdown("---")
            st.subheader("Product Performance Table (Consolidated)")
            
            # Display Merged Product Family Data with Corrected Metrics
            display_cols = [
                "Title", "Author", "Total Revenue", "Total Royalty", "Ad Spend", 
                "Ad Sales", "Total Units Sold", "Campaign Count", "ACOS %", "TACOS %"
            ]
            st.dataframe(
                metrics_df[display_cols].sort_values(by="Total Revenue", ascending=False), 
                use_container_width=True
            )
            
            # --- Warning for Unmapped Campaigns ---
            unmapped_spend = metrics_df[metrics_df['Title'] == 'Unmapped']['Ad Spend'].sum()
            if unmapped_spend > 0:
                st.warning(f"⚠️ **${unmapped_spend:,.2f}** in Ad Spend is currently **UNMAPPED**! Use the next tab to fix this.")

        # ----------------------------------------------------
        # Tab 2: Campaign Mapping & Management (Self-Service)
        # ----------------------------------------------------
        with tab2:
            st.header("Campaign Mapping & Management (Self-Service)")

            # Rule Addition Interface
            with st.form("mapping_form"):
                st.subheader("Add New Mapping Rule")
                
                # Dynamic Product Selection for ease of use
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
            
            # Show Unmapped Campaigns
            st.markdown("---")
            st.subheader("Unmapped Campaigns to Address")
            
            # Recalculate 'Mapped Product' on the raw ads data using current mappings
            ads_df_temp = ads_df.copy()
            ads_df_temp["Mapped Product"] = ads_df_temp["Campaign Name"].apply(
                 lambda x: map_campaign(x, st.session_state["mappings"])
            )

            current_unmapped = ads_df_temp[ads_df_temp["Mapped Product"] == "Unmapped"]
            
            if current_unmapped.empty:
                st.success("✅ All campaigns are currently mapped (or have zero spend)! You are good to go.")
            else:
                st.info(f"You have **{len(current_unmapped['Campaign Name'].unique())}** unique unmapped campaigns (total spend: ${current_unmapped['Ad Spend'].sum():,.2f}).")
                # Group unmapped campaigns by name to show unique ones
                unmapped_summary = current_unmapped.groupby('Campaign Name').agg(
                    {'Ad Spend': 'sum', 'Ad Sales': 'sum'}
                ).sort_values(by='Ad Spend', ascending=False).reset_index()
                
                st.dataframe(unmapped_summary, use_container_width=True)
                
            st.markdown("---")
            st.subheader("Current Mappings (Keyword → Product)")
            st.json(st.session_state["mappings"])

        # ----------------------------------------------------
        # Tab 3: Data Feed / Raw Data
        # ----------------------------------------------------
        with tab3:
            st.header("Data Feed / Raw Data View")

            st.markdown("---")
            st.subheader("Raw Advertising Data")
            st.dataframe(ads_df, use_container_width=True)
            
            st.markdown("---")
            st.subheader(f"Raw Combined Royalty Data (Filtered for {selected_month})")
            st.dataframe(raw_royalty_combined, use_container_width=True)


    else:
        st.error("⚠️ **Data processing cannot proceed.** Please check the following issues:")
        if not royalty_files or not ads_file:
            st.markdown("- **Upload Status:** Ensure both Royalty files and the Advertising file are uploaded.")
        if royalty_files and not selected_month:
            st.markdown("- **Date Selection:** Ensure a valid month is selected after uploading the royalty files.")
        if royalty_files and selected_month and royalty_df_merged.empty:
            st.markdown(f"- **Royalty Data for {selected_month}:** Could not find valid royalty data for the selected month. Check file format.")
        if ads_file and ads_df.empty:
            st.markdown("- **Advertising File:** Ensure your Ads file is a standard AdLabs export format.")
else:
    st.info("👆 Please upload all KDP Royalty files and the Advertising Data file to activate the dashboard.")
