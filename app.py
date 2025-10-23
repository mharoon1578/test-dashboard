import streamlit as st
import pandas as pd
import numpy as np
import re
from io import StringIO, BytesIO
from typing import Dict, List, Any, Tuple
import plotly.express as px
import hashlib

# --- Page Configuration ---
st.set_page_config(page_title="KDP Ads & Royalty Dashboard", layout="wide")

# --- Custom Styling ---
st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] {
    gap: 15px;
}
.stMetric {
    border: 1px solid rgba(150, 150, 150, 0.2);
    border-radius: 10px;
    padding: 15px;
    box-shadow: 0px 4px 8px rgba(0,0,0,0.1);
    transition: all 0.3s ease-in-out;
}
.stMetric:hover {
    box-shadow: 0px 6px 12px rgba(0,0,0,0.15);
}
</style>
""", unsafe_allow_html=True)

# Initialize session state
def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        "mappings": {},
        "excluded_campaigns": [],
        "current_account": None,
        "accounts": {
            "CuriousPress": {"password": hashlib.md5("curious123".encode()).hexdigest()},
            "Client A": {"password": hashlib.md5("clienta123".encode()).hexdigest()},
            "Client B": {"password": hashlib.md5("clientb123".encode()).hexdigest()}
        },
        "show_add_account": False,
        "ads_files_data": {}  # Store processed ads data
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Initialize session state
init_session_state()

# ----------------------------------------------------
# AUTHENTICATION FUNCTIONS
# ----------------------------------------------------
def check_login():
    """Check if user is logged in, show login form if not"""
    if st.session_state.current_account is None:
        st.title("KDP Ads & Royalty Dashboard - Login")
        
        with st.form("login_form"):
            username = st.selectbox("Select Account", list(st.session_state.accounts.keys()))
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            
            if submitted:
                if hashlib.md5(password.encode()).hexdigest() == st.session_state.accounts[username]["password"]:
                    st.session_state.current_account = username
                    st.success(f"Logged in as {username}")
                    st.rerun()
                else:
                    st.error("Invalid password")
        
        st.info("Default passwords:")
        st.code("CuriousPress: curious123\nClient A: clienta123\nClient B: clientb123")
        return False
    return True

def logout():
    """Logout function"""
    if st.sidebar.button("Logout"):
        st.session_state.current_account = None
        st.rerun()

# ----------------------------------------------------
# CORE STRING CLEANING UTILITY
# ----------------------------------------------------
def robust_clean_string(s: Any) -> str:
    """Aggressively cleans and standardizes strings for safe comparison."""
    if pd.isna(s): 
        return ''
    s = str(s).strip()
    s = re.sub(r'[\u200b\xa0\s]+', ' ', s)
    return s.strip().upper()

# ----------------------------------------------------
# CORE DATA PROCESSING FUNCTIONS
# ----------------------------------------------------
def load_df(uploaded_file: Any, file_type: str, header_index: int, sheet_name: str = None) -> pd.DataFrame:
    """Load DataFrame with robust error handling."""
    try:
        file_content = uploaded_file.getvalue()
        
        if uploaded_file.name.endswith(('.xlsx', '.xls')):
            content_buffer = BytesIO(file_content)
            if sheet_name:
                df = pd.read_excel(content_buffer, header=header_index, sheet_name=sheet_name)
            else:
                df = pd.read_excel(content_buffer, header=header_index)
        else:  # CSV
            content_buffer = StringIO(file_content.decode('utf-8', errors='ignore'))
            df = pd.read_csv(content_buffer, header=header_index, encoding='utf-8', on_bad_lines='skip')
        
        df.columns = df.columns.astype(str).str.strip()
        df.dropna(how='all', inplace=True)
        return df
    except Exception as e:
        st.error(f"Error loading {file_type} file: {str(e)}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False)
def get_royalty_file_metadata(uploaded_file: Any) -> Tuple[str | None, List[str]]:
    """Extract date and marketplaces from KDP royalty file."""
    file_content = uploaded_file.getvalue()
    date_str = None
    marketplaces = set()
    
    # Extract date from first line
    try:
        if uploaded_file.name.endswith('.csv'):
            first_line = StringIO(file_content.decode('utf-8', errors='ignore')).readline()
            if first_line.strip().lower().startswith('sales period'):
                parts = first_line.split(',')
                if len(parts) > 1:
                    date_str = parts[1].strip()
        elif uploaded_file.name.endswith(('.xlsx', '.xls')):
            # Try to read from the first sheet
            try:
                df_temp = pd.read_excel(BytesIO(file_content), header=None, nrows=1, sheet_name=0)
                date_str = str(df_temp.iloc[0, 1]).strip()
            except:
                pass
    except Exception:
        date_str = None
    
    # Extract marketplaces from all sheets
    try:
        if uploaded_file.name.endswith(('.xlsx', '.xls')):
            xl_file = pd.ExcelFile(BytesIO(file_content))
            for sheet_name in xl_file.sheet_names:
                df = load_df(uploaded_file, "Royalty", 1, sheet_name)
                if not df.empty and 'Marketplace' in df.columns:
                    raw_marketplaces = df['Marketplace'].astype(str).str.strip().unique().tolist()
                    marketplaces.update([m for m in raw_marketplaces if m and m != 'N/A'])
        else:
            df = load_df(uploaded_file, "Royalty", 1)
            if not df.empty and 'Marketplace' in df.columns:
                raw_marketplaces = df['Marketplace'].astype(str).str.strip().unique().tolist()
                marketplaces.update([m for m in raw_marketplaces if m and m != 'N/A'])
    except Exception:
        pass
    
    return date_str if date_str and date_str.lower() != 'nan' else None, sorted(list(marketplaces))

def process_kdp_sheet(df: pd.DataFrame, sheet_type: str) -> pd.DataFrame:
    """Process individual KDP sheet and standardize columns."""
    if df.empty:
        return pd.DataFrame()
    
    processed = pd.DataFrame()
    
    if sheet_type == "eBook Royalty":
        required_cols = ['Title', 'Author', 'Royalty', 'Net Units Sold', 'Marketplace']
        if all(col in df.columns for col in required_cols):
            processed = df[required_cols].copy()
            processed['Format'] = 'eBook'
            processed['Revenue'] = pd.to_numeric(processed['Royalty'], errors='coerce').fillna(0)
            processed['Units'] = pd.to_numeric(processed['Net Units Sold'], errors='coerce').fillna(0)
    
    elif sheet_type == "Paperback Royalty":
        required_cols = ['Title', 'Royalty', 'Units Sold', 'Marketplace']
        if all(col in df.columns for col in required_cols):
            processed = df[required_cols].copy()
            processed['Author'] = df.get('Author', 'N/A')  # Use .get() to avoid KeyError
            processed['Format'] = 'Paperback'
            processed['Revenue'] = pd.to_numeric(processed['Royalty'], errors='coerce').fillna(0)
            processed['Units'] = pd.to_numeric(processed['Units Sold'], errors='coerce').fillna(0)
    
    elif sheet_type == "Hardcover Royalty":
        required_cols = ['Title', 'Royalty', 'Units Sold', 'Marketplace']
        if all(col in df.columns for col in required_cols):
            processed = df[required_cols].copy()
            processed['Author'] = df.get('Author', 'N/A')
            processed['Format'] = 'Hardcover'
            processed['Revenue'] = pd.to_numeric(processed['Royalty'], errors='coerce').fillna(0)
            processed['Units'] = pd.to_numeric(processed['Units Sold'], errors='coerce').fillna(0)
    
    elif sheet_type == "KENP":
        required_cols = ['Title', 'eBook ASIN', 'Kindle Edition Normalized Pages (KENP)', 'Marketplace']
        if all(col in df.columns for col in required_cols):
            processed = df[required_cols].copy()
            processed['Author'] = df.get('Author', 'N/A')
            processed['Format'] = 'KENP'
            # KENP revenue is calculated differently - for now, we'll track pages read
            processed['Revenue'] = 0  # KENP revenue is separate and complex
            processed['Units'] = pd.to_numeric(processed['Kindle Edition Normalized Pages (KENP)'], errors='coerce').fillna(0)
    
    return processed

@st.cache_data
def combine_and_merge_royalty_data(royalty_files: List[Any], file_to_date_map: Dict[str, str], 
                                  selected_month: str, selected_marketplace: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Process ALL sheets from KDP files and combine data by title."""
    if not royalty_files or not selected_month:
        return pd.DataFrame(), pd.DataFrame()
    
    all_processed_data = []
    files_processed = 0
    
    selected_marketplace_cleaned = robust_clean_string(selected_marketplace)
    
    for file in royalty_files:
        file_date = file_to_date_map.get(file.name)
        
        try:
            if file.name.endswith(('.xlsx', '.xls')):
                # Process Excel file with multiple sheets
                xl_file = pd.ExcelFile(BytesIO(file.getvalue()))
                sheet_names = xl_file.sheet_names
                
                for sheet_name in sheet_names:
                    df = load_df(file, "Royalty", 1, sheet_name)
                    if df.empty:
                        # Try with header=0
                        df = load_df(file, "Royalty", 0, sheet_name)
                    
                    if not df.empty:
                        processed = process_kdp_sheet(df, sheet_name)
                        if not processed.empty:
                            processed['File Date'] = file_date
                            processed['Sheet Name'] = sheet_name
                            all_processed_data.append(processed)
            
            else:
                # Process CSV file (single sheet)
                df = load_df(file, "Royalty", 1)
                if df.empty:
                    df = load_df(file, "Royalty", 0)
                
                if not df.empty:
                    processed = process_kdp_sheet(df, "eBook Royalty")  # Assume CSV is eBook
                    if not processed.empty:
                        processed['File Date'] = file_date
                        processed['Sheet Name'] = 'CSV Data'
                        all_processed_data.append(processed)
            
            if all_processed_data:
                files_processed += 1
                
        except Exception as e:
            st.error(f"Error processing file {file.name}: {str(e)}")
            continue
    
    if not all_processed_data:
        st.error(f"No valid royalty data found for {selected_month} in {selected_marketplace}")
        return pd.DataFrame(), pd.DataFrame()
    
    # Combine all data
    combined_df = pd.concat(all_processed_data, ignore_index=True)
    
    # Filter by selected month
    if 'File Date' in combined_df.columns:
        combined_df = combined_df[combined_df['File Date'] == selected_month].copy()
        if combined_df.empty:
            st.error(f"No data found for {selected_month}")
            return pd.DataFrame(), pd.DataFrame()
    
    # Filter by selected marketplace
    if selected_marketplace != "All Marketplaces" and 'Marketplace' in combined_df.columns:
        combined_df['Marketplace_Cleaned'] = combined_df['Marketplace'].apply(robust_clean_string)
        combined_df = combined_df[combined_df['Marketplace_Cleaned'] == selected_marketplace_cleaned].copy()
        combined_df.drop(columns=['Marketplace_Cleaned'], inplace=True, errors='ignore')
        
        if combined_df.empty:
            st.error(f"No data found for {selected_marketplace}")
            return pd.DataFrame(), pd.DataFrame()
    
    # Group by Title and aggregate all formats
    # Get the first author for each title (prioritize eBook author if available)
    ebook_authors = combined_df[combined_df['Format'] == 'eBook'].drop_duplicates('Title')
    if not ebook_authors.empty:
        author_map = ebook_authors.set_index('Title')['Author']
        combined_df['Author'] = combined_df.apply(
            lambda row: author_map.get(row['Title'], row['Author']), axis=1
        )
    
    # Aggregate by Title
    merged_royalty_df = combined_df.groupby(['Title', 'Author'], as_index=False).agg({
        'Revenue': 'sum',
        'Units': 'sum'
    }).rename(columns={'Revenue': 'Total Royalty', 'Units': 'Total Units Sold'})
    
    # Filter out zero revenue
    merged_royalty_df = merged_royalty_df[merged_royalty_df['Total Royalty'] > 0]
    
    st.success(f"Processed **{files_processed}** files with **{len(combined_df)}** total records into **{len(merged_royalty_df)}** unique titles.")
    
    return merged_royalty_df, combined_df

def clean_ads_data(ads_file: Any, marketplace: str = None) -> pd.DataFrame:
    """Standardize Advertising data columns."""
    df = load_df(ads_file, "Ads", 0)
    if df.empty:
        return pd.DataFrame()
    
    # Add marketplace information if provided
    if marketplace:
        df['Marketplace'] = marketplace
    
    # Map columns to standard names
    column_mapping = {}
    for col in df.columns:
        col_lower = col.strip().lower()
        if 'campaign' in col_lower and 'name' not in column_mapping:
            column_mapping['Campaign Name'] = col
        elif col_lower == 'spend':
            column_mapping['Ad Spend'] = col
        elif col_lower == 'sales':
            column_mapping['Ad Sales'] = col
        elif col_lower == 'orders':
            column_mapping['Ad Units Sold'] = col
    
    # Rename columns
    df = df.rename(columns={v: k for k, v in column_mapping.items()})
    
    # Check required columns
    required_cols = ['Campaign Name', 'Ad Spend', 'Ad Sales', 'Ad Units Sold']
    missing_cols = [col for col in required_cols if col not in df.columns]
    
    if missing_cols:
        st.error(f"Missing required columns in ads file: {', '.join(missing_cols)}")
        return pd.DataFrame()
    
    # Convert numeric columns
    for col in ['Ad Spend', 'Ad Sales', 'Ad Units Sold']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    return df

def map_campaign(name: str, mappings: Dict[str, str]) -> str:
    """Apply campaign mappings with robust error handling."""
    if pd.isna(name):
        return "Unmapped"
    
    name = str(name).strip().lower()
    for rule, product in mappings.items():
        try:
            if re.search(rule.lower(), name, re.IGNORECASE):
                return product
        except re.error:
            if rule.lower() in name:
                return product
    return "Unmapped"

def calculate_metrics(ads_df: pd.DataFrame, royalties_df: pd.DataFrame, mappings: Dict[str, str], excluded_campaigns: List[str]) -> pd.DataFrame:
    """Calculate comprehensive metrics with proper unmapped handling."""
    if ads_df.empty or royalties_df.empty:
        return pd.DataFrame()
    
    # Filter out excluded campaigns
    if excluded_campaigns:
        ads_df = ads_df[~ads_df['Campaign Name'].isin(excluded_campaigns)]
    
    # Apply mappings
    ads_df['Mapped Product'] = ads_df['Campaign Name'].apply(lambda x: map_campaign(x, mappings))
    
    # Aggregate ad data by product
    ad_summary = ads_df.groupby('Mapped Product').agg({
        'Ad Spend': 'sum',
        'Ad Sales': 'sum',
        'Ad Units Sold': 'sum',
        'Campaign Name': 'count'
    }).reset_index().rename(columns={'Campaign Name': 'Campaign Count'})
    
    # Merge with royalty data
    merged = pd.merge(royalties_df, ad_summary, how='outer',
                      left_on='Title', right_on='Mapped Product')
    
    # Fill missing values
    merged['Title'].fillna(merged['Mapped Product'], inplace=True)
    merged.drop(columns=['Mapped Product'], inplace=True, errors='ignore')
    
    numeric_cols = ['Total Royalty', 'Total Units Sold', 'Ad Spend', 'Ad Sales', 'Ad Units Sold', 'Campaign Count']
    for col in numeric_cols:
        if col in merged.columns:
            merged[col].fillna(0, inplace=True)
    
    # Calculate metrics
    merged['Total Revenue'] = merged['Total Royalty']  # Total Revenue is just royalty
    
    # Calculate Profit (Total Revenue - Ad Spend)
    merged['Profit'] = merged['Total Revenue'] - merged['Ad Spend']
    
    # FIXED: Only calculate ACOS for products with actual Ad Sales
    merged['ACOS %'] = np.where(
        (merged['Ad Sales'] > 0) & (merged['Title'] != 'Unmapped'),
        (merged['Ad Spend'] / merged['Ad Sales']) * 100,
        0
    )
    
    # FIXED: Only calculate TACOS for products with actual Total Revenue
    merged['TACOS %'] = np.where(
        (merged['Total Revenue'] > 0) & (merged['Title'] != 'Unmapped'),
        (merged['Ad Spend'] / merged['Total Revenue']) * 100,
        0
    )
    
    # Convert to appropriate types
    merged['Total Units Sold'] = merged['Total Units Sold'].astype(int)
    merged['Campaign Count'] = merged['Campaign Count'].astype(int)
    
    return merged

def render_mapping_management(royalty_df: pd.DataFrame):
    """Render mapping management interface."""
    st.markdown("---")
    st.subheader("Current Mappings (Keyword → Product)")
    
    if not st.session_state["mappings"]:
        st.info("No mapping rules defined yet.")
        return
    
    for rule, product in dict(st.session_state["mappings"]).items():
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            st.code(rule)
        with col2:
            st.write(product)
        with col3:
            if st.button("🗑️", key=f"del_{rule}"):
                del st.session_state["mappings"][rule]
                st.rerun()

def render_excluded_campaigns(ads_df: pd.DataFrame):
    """Render excluded campaigns management interface."""
    st.markdown("---")
    st.subheader("Excluded Campaigns Management")
    
    if ads_df.empty:
        st.info("No advertising data available to exclude.")
        return
    
    # Get all campaign names
    all_campaigns = ads_df['Campaign Name'].unique().tolist()
    
    # Show current excluded campaigns
    if st.session_state["excluded_campaigns"]:
        st.write("**Currently Excluded Campaigns:**")
        for campaign in st.session_state["excluded_campaigns"]:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.write(campaign)
            with col2:
                if st.button("Remove", key=f"remove_excl_{campaign}"):
                    st.session_state["excluded_campaigns"].remove(campaign)
                    st.rerun()
    else:
        st.info("No campaigns are currently excluded.")
    
    # Add new excluded campaigns
    st.write("**Add Campaigns to Exclude:**")
    available_to_exclude = [c for c in all_campaigns if c not in st.session_state["excluded_campaigns"]]
    
    if available_to_exclude:
        selected_campaigns = st.multiselect(
            "Select campaigns to exclude from calculations",
            available_to_exclude
        )
        
        if st.button("Exclude Selected Campaigns"):
            for campaign in selected_campaigns:
                if campaign not in st.session_state["excluded_campaigns"]:
                    st.session_state["excluded_campaigns"].append(campaign)
            st.success(f"Added {len(selected_campaigns)} campaigns to exclusion list.")
            st.rerun()
    else:
        st.info("All campaigns are already excluded.")

def display_mapping_stats(ads_df: pd.DataFrame):
    """Display mapping statistics."""
    if ads_df.empty:
        return
    
    ads_df_temp = ads_df.copy()
    ads_df_temp['Mapped Product'] = ads_df_temp['Campaign Name'].apply(
        lambda x: map_campaign(x, st.session_state["mappings"])
    )
    
    # Filter out excluded campaigns from stats
    if st.session_state["excluded_campaigns"]:
        ads_df_temp = ads_df_temp[~ads_df_temp['Campaign Name'].isin(st.session_state["excluded_campaigns"])]
    
    total_spend = ads_df_temp['Ad Spend'].sum()
    unmapped = ads_df_temp[ads_df_temp['Mapped Product'] == 'Unmapped']
    unmapped_spend = unmapped['Ad Spend'].sum()
    
    if total_spend > 0:
        mapped_percentage = ((total_spend - unmapped_spend) / total_spend) * 100
        st.metric("Mapping Coverage", f"{mapped_percentage:.1f}%")
    
    if not unmapped.empty:
        st.warning(f"⚠️ **${unmapped_spend:,.2f}** in Ad Spend is currently **UNMAPPED**!")
        unmapped_summary = unmapped.groupby('Campaign Name').agg({
            'Ad Spend': 'sum',
            'Ad Sales': 'sum'
        }).sort_values('Ad Spend', ascending=False).reset_index()
        st.dataframe(unmapped_summary, use_container_width=True)

# ----------------------------------------------------
# MAIN APPLICATION
# ----------------------------------------------------
if check_login():
    # ----------------------------------------------------
    # SIDEBAR: UPLOAD & CONFIG
    # ----------------------------------------------------
    st.sidebar.header(f"Upload & Settings - {st.session_state.current_account}")
    logout()
    
    # Account management
    with st.sidebar.expander("Account Management"):
        if st.button("Add New Account"):
            st.session_state.show_add_account = True
    
    # Add new account dialog
    if st.session_state.get("show_add_account", False):
        with st.sidebar.form("add_account_form"):
            new_account = st.text_input("New Account Name")
            new_password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Add Account")
            
            if submitted and new_account:
                st.session_state.accounts[new_account] = {
                    "password": hashlib.md5(new_password.encode()).hexdigest()
                }
                st.success(f"Account {new_account} added successfully!")
                st.session_state.show_add_account = False
                st.rerun()
    
    royalty_files = st.sidebar.file_uploader(
        "2. Upload KDP Royalty Files (Excel with multiple sheets)",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        help="Upload Excel files containing eBook, Paperback, Hardcover, and KENP sheets"
    )
    
    # NEW: Multiple advertising files with marketplace selection
    st.sidebar.subheader("3. Upload Advertising Data")
    ads_files = st.sidebar.file_uploader(
        "Upload Advertising Data (AdLabs Export)",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        help="Upload your AdLabs campaign export files for different marketplaces"
    )
    
    # Store ads files with marketplace info
    ads_files_with_marketplace = []
    if ads_files:
        for file in ads_files:
            with st.sidebar.expander(f"Configure {file.name}"):
                marketplace = st.selectbox(
                    f"Marketplace for {file.name}",
                    ["Amazon.com", "Amazon.co.uk", "Amazon.ca", "Amazon.de", "Amazon.fr", "Amazon.es", "Amazon.it", "Amazon.jp", "Amazon.au", "Other"],
                    key=f"marketplace_{file.name}"
                )
                ads_files_with_marketplace.append((file, marketplace))
    
    # Extract metadata
    file_to_date_map = {}
    unique_dates = set()
    all_marketplaces = set()
    
    if royalty_files:
        for file in royalty_files:
            date_found, marketplaces_found = get_royalty_file_metadata(file)
            if date_found:
                file_to_date_map[file.name] = date_found
                unique_dates.add(date_found)
            all_marketplaces.update(marketplaces_found)
    
    # Date selector
    selected_month = None
    if unique_dates:
        sorted_dates = sorted(list(unique_dates), reverse=True)
        selected_month = st.sidebar.selectbox("4. Reporting Month", sorted_dates, index=0)
    else:
        selected_month = st.sidebar.text_input("4. Reporting Month (Manual)", value="September 2025")
    
    # Marketplace selector
    selected_marketplace = None
    if all_marketplaces:
        marketplace_options = ["All Marketplaces"] + sorted(list(all_marketplaces))
        selected_marketplace = st.sidebar.selectbox("5. Marketplace", marketplace_options, index=0)
    else:
        marketplace_options = ["All Marketplaces", "Amazon.com", "Amazon.co.uk", "Amazon.ca"]
        selected_marketplace = st.sidebar.selectbox("5. Marketplace (Manual)", marketplace_options, index=0)
    
    # ----------------------------------------------------
    # MAIN DASHBOARD
    # ----------------------------------------------------
    if royalty_files and ads_files and selected_month and selected_marketplace:
        
        royalty_df_merged, raw_royalty_combined = combine_and_merge_royalty_data(
            royalty_files, file_to_date_map, selected_month, selected_marketplace
        )
        
        # Process all advertising files
        all_ads_data = []
        for file, marketplace in ads_files_with_marketplace:
            ads_df = clean_ads_data(file, marketplace)
            if not ads_df.empty:
                all_ads_data.append(ads_df)
        
        if all_ads_data:
            ads_df_combined = pd.concat(all_ads_data, ignore_index=True)
            
            # Filter ads data by selected marketplace
            if selected_marketplace != "All Marketplaces" and 'Marketplace' in ads_df_combined.columns:
                ads_df_combined = ads_df_combined[ads_df_combined['Marketplace'] == selected_marketplace]
        else:
            ads_df_combined = pd.DataFrame()
        
        if not royalty_df_merged.empty and not ads_df_combined.empty:
            
            metrics_df = calculate_metrics(
                ads_df_combined, 
                royalty_df_merged, 
                st.session_state["mappings"],
                st.session_state["excluded_campaigns"]
            )
            
            tab1, tab2, tab3 = st.tabs(["📊 Performance Summary", "📝 Campaign Mapping", "📂 Raw Data"])
            
            with tab1:
                st.header(f"Performance Summary — {st.session_state.current_account} ({selected_marketplace}, {selected_month})")
                
                # Calculate totals
                total_ad_spend = metrics_df["Ad Spend"].sum()
                total_ad_sales = metrics_df["Ad Sales"].sum()
                total_royalty = metrics_df["Total Royalty"].sum()
                total_revenue = total_royalty
                total_profit = metrics_df["Profit"].sum()
                total_units = metrics_df["Total Units Sold"].sum()
                
                overall_acos = (total_ad_spend / total_ad_sales * 100) if total_ad_sales > 0 else 0
                overall_tacos = (total_ad_spend / total_revenue * 100) if total_revenue > 0 else 0
                
                # Display metrics
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Revenue", f"${total_revenue:,.2f}")
                    st.metric("Total Profit", f"${total_profit:,.2f}")
                with col2:
                    st.metric("Overall ACOS", f"{overall_acos:.1f}%")
                    st.metric("Overall TACOS", f"{overall_tacos:.1f}%")
                with col3:
                    st.metric("Total Units Sold", f"{int(total_units):,}")
                    st.metric("Total Ad Spend", f"${total_ad_spend:,.2f}")
                
                st.markdown("---")
                st.subheader("Product Performance")
                
                # Revenue breakdown chart - FIXED: Filter out Unmapped
                revenue_by_product = metrics_df.groupby('Title')[['Total Royalty', 'Ad Sales']].sum().reset_index()
                
                # FIXED: Filter out Unmapped from visualization
                revenue_by_product = revenue_by_product[revenue_by_product['Title'] != 'Unmapped']
                
                # Only show products with actual revenue
                revenue_by_product = revenue_by_product[revenue_by_product['Total Royalty'] + revenue_by_product['Ad Sales'] > 0]
                
                fig_revenue = px.bar(
                    revenue_by_product,
                    x='Title',
                    y=['Total Royalty', 'Ad Sales'],
                    title='Total Revenue Breakdown by Product (Royalty vs. Ad Sales)',
                    labels={'value': 'Revenue ($)', 'variable': 'Revenue Type', 'Title': 'Product'},
                    height=500
                )
                fig_revenue.update_layout(xaxis={'categoryorder': 'total descending'})
                st.plotly_chart(fig_revenue, use_container_width=True)
                
                # Performance table - FIXED: Filter out Unmapped
                display_df = metrics_df[metrics_df['Title'] != 'Unmapped'].copy()
                
                display_cols = [
                    "Title", "Author", "Total Revenue", "Profit", "Ad Spend", 
                    "Ad Sales", "Total Units Sold", "Campaign Count", "ACOS %", "TACOS %"
                ]
                st.dataframe(
                    display_df[display_cols].sort_values("Total Revenue", ascending=False),
                    use_container_width=True
                )
                
                # Show unmapped warning if needed
                unmapped_spend = metrics_df[metrics_df['Title'] == 'Unmapped']['Ad Spend'].sum()
                if unmapped_spend > 0:
                    st.warning(f"⚠️ **${unmapped_spend:,.2f}** in Ad Spend is currently **UNMAPPED**! Use the Campaign Mapping tab to fix this.")
            
            with tab2:
                st.header("Campaign Mapping & Management")
                
                with st.form("mapping_form"):
                    st.subheader("Add New Mapping Rule")
                    
                    product_list = sorted(royalty_df_merged['Title'].unique())
                    new_product = st.selectbox("Map To Product Title", product_list, key="map_select")
                    new_rule = st.text_input("Mapping Keyword", key="map_rule", 
                                           help="Enter keyword that appears in campaign names")
                    
                    submitted = st.form_submit_button("Add Mapping Rule")
                    
                    if submitted:
                        if new_rule and new_product:
                            st.session_state["mappings"][new_rule.lower()] = new_product
                            st.success(f"Rule added: '{new_rule}' → {new_product}")
                            st.rerun()
                        else:
                            st.warning("Please enter both keyword and select a product.")
                
                render_mapping_management(royalty_df_merged)
                render_excluded_campaigns(ads_df_combined)
                display_mapping_stats(ads_df_combined)
            
            with tab3:
                st.header("Raw Data View")
                
                st.subheader("Advertising Data")
                st.dataframe(ads_df_combined, use_container_width=True)
                
                st.subheader("Processed Royalty Data")
                st.dataframe(raw_royalty_combined, use_container_width=True)
        
        else:
            st.error("⚠️ Dashboard cannot load. Please check:")
            if royalty_df_merged.empty:
                st.markdown("- Royalty data processing failed")
            if ads_df_combined.empty:
                st.markdown("- Advertising data loading failed")

    else:
        st.info("👆 Please upload KDP Royalty files and Advertising data to activate the dashboard.")
