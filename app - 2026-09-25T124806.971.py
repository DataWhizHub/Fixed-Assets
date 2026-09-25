"""
Fixed Asset Management System - KMN
------------------------------------
A Streamlit application backed by Google Sheets for managing fixed assets
across the Chilaw and Palavi offices.

Sections:
    1. Asset Register
    2. Asset Transfers
    3. Annual Asset Verification
    4. Asset Disposal
    5. Search & Filters

Data storage: Google Sheets (via gspread + a Google Service Account)
"""

import re
import hashlib
import datetime as dt

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials


# ============================================================================
# CONFIG
# ============================================================================

SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1f6qisix5WFGTxLHNQL4xwvX1vp__U7DYkuJHRy72QS0/edit"

OFFICES = ["CHILAW", "PALAVI"]
OFFICE_CODE = {"CHILAW": "CH", "PALAVI": "PA"}

CONDITIONS = ["New", "Good", "Fair", "Poor", "Damaged"]

ASSET_STATUS_OPTIONS = ["Found", "Missing"]
LOCATION_STATUS_OPTIONS = ["Not Changed", "Changed"]
OTHER_STATUS_OPTIONS = ["Not Damaged", "Damaged"]

MAX_ADMINS = 1
MAX_USERS = 3

USERS_COLUMNS = ["Username", "Password Hash", "Full Name", "Role", "Office", "Created At"]

ASSET_COLUMNS = [
    "Item Code", "Office", "Location", "Sub Location", "Item Name",
    "Main Category", "Sub Category", "Description", "Brand/Model",
    "Serial No", "Date of Purchase", "Purchased From", "User", "Condition",
    "Amount", "Status", "Entered By", "Entered At", "Last Updated",
]

TRANSFER_COLUMNS = [
    "Transfer ID", "Item Code", "From Office", "From Location", "From User",
    "To Office", "To Location", "To User", "Transfer Date", "Transferred By",
]

VERIFICATION_COLUMNS = [
    "Verification ID", "Item Code", "Verification Date", "Asset Status",
    "Location Status", "Other Status", "Verified By", "Office at Verification",
    "Location at Verification",
]

DISPOSAL_COLUMNS = [
    "Request ID", "Item Code", "Requested By", "Request Date", "Reason",
    "Status", "Reviewed By", "Review Date", "Review Notes",
]

REQUIRED_ASSET_FIELDS = ["Office", "Location", "Item Code", "Item Name",
                          "Main Category", "User", "Condition"]


# ============================================================================
# GOOGLE SHEETS CONNECTION
# ============================================================================

@st.cache_resource(show_spinner=False)
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    client = get_gspread_client()
    return client.open_by_url(SPREADSHEET_URL)


def get_or_create_worksheet(sheet_name: str, columns: list):
    ss = get_spreadsheet()
    try:
        ws = ss.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=sheet_name, rows=1000, cols=len(columns) + 2)
        ws.append_row(columns)
        return ws

    header = ws.row_values(1)
    if not header:
        ws.append_row(columns)
    elif header != columns:
        # add any missing columns at the end without destroying existing data
        missing = [c for c in columns if c not in header]
        if missing:
            new_header = header + missing
            ws.update("A1", [new_header])
    return ws


@st.cache_data(ttl=20, show_spinner=False)
def load_df(sheet_name: str, columns: list) -> pd.DataFrame:
    ws = get_or_create_worksheet(sheet_name, columns)
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    for c in columns:
        if c not in df.columns:
            df[c] = ""
    if not df.empty:
        df = df[columns + [c for c in df.columns if c not in columns]]
    else:
        df = pd.DataFrame(columns=columns)
    return df


def clear_caches():
    load_df.clear()


def append_row(sheet_name: str, columns: list, row: dict):
    ws = get_or_create_worksheet(sheet_name, columns)
    header = ws.row_values(1)
    ordered = [str(row.get(c, "")) for c in header]
    ws.append_row(ordered)
    clear_caches()


def update_row_by_key(sheet_name: str, columns: list, key_col: str, key_val: str, updates: dict):
    ws = get_or_create_worksheet(sheet_name, columns)
    header = ws.row_values(1)
    cell = ws.find(str(key_val), in_column=header.index(key_col) + 1)
    if cell is None:
        return False
    row_idx = cell.row
    row_vals = ws.row_values(row_idx)
    row_vals += [""] * (len(header) - len(row_vals))
    for k, v in updates.items():
        if k in header:
            row_vals[header.index(k)] = str(v)
    ws.update(f"A{row_idx}", [row_vals])
    clear_caches()
    return True


# ============================================================================
# USER ACCOUNTS (1 Admin + up to 3 Users, each with their own username/password)
# ============================================================================

def hash_password(password: str) -> str:
    # Salted so two accounts with the same password don't produce the same hash.
    return hashlib.sha256(("kmn-fams::" + password).encode("utf-8")).hexdigest()


def get_users_df() -> pd.DataFrame:
    return load_df("Users", USERS_COLUMNS)


def account_counts(udf: pd.DataFrame):
    admins = len(udf[udf["Role"] == "Admin"]) if not udf.empty else 0
    users = len(udf[udf["Role"] == "User"]) if not udf.empty else 0
    return admins, users


def create_account(username: str, password: str, full_name: str, role: str, office: str):
    username = username.strip()
    if not username or not password:
        return False, "Username and password are required."
    if not full_name.strip():
        return False, "Full name is required."

    udf = get_users_df()
    if not udf.empty and username.lower() in udf["Username"].str.lower().tolist():
        return False, "That username is already taken — please choose another."

    admins, users = account_counts(udf)
    if role == "Admin" and admins >= MAX_ADMINS:
        return False, f"Only {MAX_ADMINS} Admin account is allowed, and it already exists."
    if role == "User" and users >= MAX_USERS:
        return False, f"Only {MAX_USERS} User accounts are allowed, and that limit has been reached."

    append_row("Users", USERS_COLUMNS, {
        "Username": username, "Password Hash": hash_password(password),
        "Full Name": full_name.strip(), "Role": role, "Office": office,
        "Created At": now_str(),
    })
    return True, f"Account created for {full_name.strip()} ({role}). You can log in now."


def authenticate(username: str, password: str):
    udf = get_users_df()
    if udf.empty or not username.strip():
        return None
    match = udf[udf["Username"].str.lower() == username.strip().lower()]
    if match.empty:
        return None
    row = match.iloc[0]
    if str(row["Password Hash"]) == hash_password(password):
        return row
    return None


def login_or_signup_screen():
    st.title("Fixed Asset Management System")
    st.caption("KMN | Chilaw & Palavi Offices")

    udf = get_users_df()
    admins, users = account_counts(udf)

    tab_login, tab_signup = st.tabs(["🔑 Log In", "🆕 Create Account"])

    with tab_login:
        with st.form("login_form"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log In", use_container_width=True, type="primary")
        if submitted:
            row = authenticate(u, p)
            if row is None:
                st.error("Invalid username or password.")
            else:
                st.session_state["auth_username"] = row["Username"]
                st.session_state["auth_full_name"] = row["Full Name"]
                st.session_state["auth_role"] = row["Role"]
                st.session_state["auth_office"] = row["Office"]
                st.rerun()
        if udf.empty:
            st.info("No accounts exist yet — create the Admin account first under **Create Account**.")

    with tab_signup:
        st.caption(f"Accounts created so far: **{admins}/{MAX_ADMINS} Admin**, **{users}/{MAX_USERS} Users**")
        available_roles = []
        if admins < MAX_ADMINS:
            available_roles.append("Admin")
        if users < MAX_USERS:
            available_roles.append("User")

        if not available_roles:
            st.info(f"All accounts ({MAX_ADMINS} Admin + {MAX_USERS} Users) have already been created. "
                     "Ask an existing Admin if you need access, or log in above.")
        else:
            with st.form("signup_form"):
                full_name = st.text_input("Full Name")
                role = st.selectbox("Role", available_roles,
                                     help="One Admin account approves disposals. Up to three User accounts "
                                          "can register, transfer, verify and search assets.")
                office = st.selectbox("Office", ["(not office-specific)"] + OFFICES)
                new_username = st.text_input("Choose a Username")
                new_password = st.text_input("Choose a Password", type="password")
                confirm_password = st.text_input("Confirm Password", type="password")
                signup_submit = st.form_submit_button("Create Account", use_container_width=True)
            if signup_submit:
                if new_password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    ok, msg = create_account(
                        new_username, new_password, full_name, role,
                        "" if office == "(not office-specific)" else office,
                    )
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)


def require_login():
    if "auth_username" not in st.session_state:
        login_or_signup_screen()
        st.stop()


# ============================================================================
# HELPERS
# ============================================================================

def now_str():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return dt.date.today().strftime("%Y-%m-%d")


def next_id(df: pd.DataFrame, id_col: str, prefix: str) -> str:
    if df.empty or id_col not in df.columns:
        return f"{prefix}-0001"
    nums = []
    for v in df[id_col]:
        m = re.search(r"(\d+)$", str(v))
        if m:
            nums.append(int(m.group(1)))
    nxt = (max(nums) + 1) if nums else 1
    return f"{prefix}-{nxt:04d}"


def category_abbrev(text: str) -> str:
    words = re.findall(r"[A-Za-z]+", text or "")
    if not words:
        return "GEN"
    if len(words) == 1:
        return words[0][:2].upper()
    return "".join(w[0] for w in words[:3]).upper()


def suggest_item_code(office: str, main_category: str, df: pd.DataFrame) -> str:
    office_code = OFFICE_CODE.get(office, "XX")
    cat_code = category_abbrev(main_category) if main_category else "GEN"
    prefix = f"KMN/{office_code}/{cat_code}/"
    nums = []
    if not df.empty and "Item Code" in df.columns:
        for code in df["Item Code"]:
            if str(code).startswith(prefix):
                m = re.search(r"(\d+)$", str(code))
                if m:
                    nums.append(int(m.group(1)))
    nxt = (max(nums) + 1) if nums else 1
    return f"{prefix}{nxt:03d}"


def suggestable_select(label: str, existing_values: list, key: str, required: bool = False):
    """A selectbox that offers previously-entered values, with an 'Add New' escape hatch
    that reveals a free-text input. Mimics autocomplete/recommend-as-you-type behaviour."""
    options = sorted({v for v in existing_values if str(v).strip()})
    add_new_label = "➕ Add New..."
    choice = st.selectbox(label, options=["(select)"] + options + [add_new_label], key=f"{key}_sb")
    if choice == add_new_label:
        val = st.text_input(f"New {label}", key=f"{key}_new")
    elif choice == "(select)":
        val = ""
    else:
        val = choice
    if required and not val:
        st.caption(f":red[{label} is required]")
    return val


def asset_lookup_block(df_assets: pd.DataFrame, key_prefix: str):
    """Common 'select Item Code -> show existing details' block used by
    Transfers, Verification and Disposal sections."""
    active_df = df_assets[df_assets["Status"] != "Disposed"] if not df_assets.empty else df_assets
    codes = sorted(active_df["Item Code"].unique()) if not active_df.empty else []
    item_code = st.selectbox("Item Code", ["(select)"] + codes, key=f"{key_prefix}_item_code")
    if item_code == "(select)" or not item_code:
        return None, None
    row = active_df[active_df["Item Code"] == item_code].iloc[0]

    st.markdown("**Existing Asset Details**")
    c1, c2, c3 = st.columns(3)
    c1.text_input("Office", row.get("Office", ""), disabled=True, key=f"{key_prefix}_o")
    c2.text_input("Location", row.get("Location", ""), disabled=True, key=f"{key_prefix}_l")
    c3.text_input("Sub Location", row.get("Sub Location", ""), disabled=True, key=f"{key_prefix}_sl")
    c4, c5, c6 = st.columns(3)
    c4.text_input("Item Name", row.get("Item Name", ""), disabled=True, key=f"{key_prefix}_in")
    c5.text_input("Main Category", row.get("Main Category", ""), disabled=True, key=f"{key_prefix}_mc")
    c6.text_input("User", row.get("User", ""), disabled=True, key=f"{key_prefix}_u")
    st.text_area("Description", row.get("Description", ""), disabled=True, key=f"{key_prefix}_desc", height=60)
    st.text_input("Condition", row.get("Condition", ""), disabled=True, key=f"{key_prefix}_cond")

    return item_code, row


# ============================================================================
# SECTION 1: ASSET REGISTER
# ============================================================================

def page_asset_register():
    st.header("🗂️ Asset Register")
    df = load_df("Assets", ASSET_COLUMNS)

    default_office_idx = 0
    remembered_office = st.session_state.get("register_office") or st.session_state.get("auth_office")
    if remembered_office in OFFICES:
        default_office_idx = OFFICES.index(remembered_office)

    with st.form("asset_register_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            office = st.selectbox("Office *", OFFICES, index=default_office_idx)
        with c2:
            location = suggestable_select("Location *", df["Location"].tolist() if not df.empty else [],
                                           key="reg_location", required=True)

        c3, c4 = st.columns(2)
        with c3:
            sub_location = st.text_input("Sub Location")
        with c4:
            main_category = suggestable_select("Main Category *",
                                                 df["Main Category"].tolist() if not df.empty else [],
                                                 key="reg_main_cat", required=True)

        c5, c6 = st.columns(2)
        with c5:
            sub_category = st.text_input("Sub Category")
        with c6:
            item_name = st.text_input("Item Name *")

        description = st.text_area("Description", height=70)

        c7, c8 = st.columns(2)
        with c7:
            brand_model = st.text_input("Brand / Model")
        with c8:
            serial_no = st.text_input("Serial No")

        c9, c10 = st.columns(2)
        with c9:
            date_of_purchase = st.date_input("Date of Purchase", value=None,
                                              min_value=dt.date(1990, 1, 1), max_value=dt.date.today())
        with c10:
            purchased_from = st.text_input("Purchased From")

        c11, c12, c13 = st.columns(3)
        with c11:
            user = st.text_input("User *")
        with c12:
            condition = st.selectbox("Condition *", CONDITIONS)
        with c13:
            amount = st.number_input("Amount (LKR)", min_value=0.0, step=100.0, format="%.2f")

        suggested_code = suggest_item_code(office, main_category, df)
        item_code = st.text_input("Item Code *", value=suggested_code,
                                   help="Auto-suggested as KMN/OfficeCode/CategoryCode/Number. Edit if needed.")

        entered_by = st.session_state.get("auth_full_name", "")
        st.caption(f"Entered by: **{entered_by}**")

        submitted = st.form_submit_button("💾 Save Asset", use_container_width=True)

    if submitted:
        st.session_state["register_office"] = office
        errors = []
        values = {
            "Office": office, "Location": location, "Item Code": item_code,
            "Item Name": item_name, "Main Category": main_category,
            "User": user, "Condition": condition,
        }
        for f in REQUIRED_ASSET_FIELDS:
            if not str(values.get(f, "")).strip():
                errors.append(f)

        if not df.empty and item_code in df["Item Code"].values:
            errors.append("Item Code (already exists)")

        if errors:
            st.error("Please complete/fix required fields: " + ", ".join(errors))
        else:
            row = {
                "Item Code": item_code, "Office": office, "Location": location,
                "Sub Location": sub_location, "Item Name": item_name,
                "Main Category": main_category, "Sub Category": sub_category,
                "Description": description, "Brand/Model": brand_model,
                "Serial No": serial_no,
                "Date of Purchase": date_of_purchase.strftime("%Y-%m-%d") if date_of_purchase else "",
                "Purchased From": purchased_from, "User": user, "Condition": condition,
                "Amount": amount, "Status": "Active", "Entered By": entered_by,
                "Entered At": now_str(), "Last Updated": now_str(),
            }
            append_row("Assets", ASSET_COLUMNS, row)
            st.success(f"✅ Asset **{item_code}** saved successfully.")
            st.rerun()


# ============================================================================
# SECTION 2: ASSET TRANSFERS
# ============================================================================

def page_asset_transfers():
    st.header("🔁 Asset Transfers")
    df = load_df("Assets", ASSET_COLUMNS)

    if df.empty:
        st.info("No assets registered yet.")
        return

    item_code, row = asset_lookup_block(df, "xfer")
    if item_code is None:
        return

    st.divider()
    st.markdown("**Transfer Details**")
    c1, c2, c3 = st.columns(3)
    with c1:
        to_office = st.selectbox("Transfer to Office *", OFFICES,
                                  index=OFFICES.index(row["Office"]) if row["Office"] in OFFICES else 0)
    with c2:
        to_location = suggestable_select("Transfer to Location *", df["Location"].tolist(), key="xfer_to_loc",
                                          required=True)
    with c3:
        to_user = st.text_input("Transfer to User *")

    transferred_by = st.session_state.get("auth_full_name", "")
    st.caption(f"Transferred by: **{transferred_by}**")

    if st.button("🚚 Transfer", use_container_width=True, type="primary"):
        errors = []
        if not to_office:
            errors.append("Transfer to Office")
        if not to_location:
            errors.append("Transfer to Location")
        if not to_user:
            errors.append("Transfer to User")

        if errors:
            st.error("Please complete required fields: " + ", ".join(errors))
        else:
            tdf = load_df("Transfers", TRANSFER_COLUMNS)
            transfer_id = next_id(tdf, "Transfer ID", "TRF")
            append_row("Transfers", TRANSFER_COLUMNS, {
                "Transfer ID": transfer_id, "Item Code": item_code,
                "From Office": row["Office"], "From Location": row["Location"], "From User": row["User"],
                "To Office": to_office, "To Location": to_location, "To User": to_user,
                "Transfer Date": now_str(), "Transferred By": transferred_by,
            })
            update_row_by_key("Assets", ASSET_COLUMNS, "Item Code", item_code, {
                "Office": to_office, "Location": to_location, "User": to_user,
                "Last Updated": now_str(),
            })
            st.success(f"✅ Transfer successful — **{item_code}** moved to {to_office} / {to_location} / {to_user}.")
            st.rerun()


# ============================================================================
# SECTION 3: ANNUAL ASSET VERIFICATION
# ============================================================================

def page_annual_verification():
    st.header("✅ Annual Asset Verification")
    df = load_df("Assets", ASSET_COLUMNS)

    if df.empty:
        st.info("No assets registered yet.")
        return

    item_code, row = asset_lookup_block(df, "ver")
    if item_code is None:
        return

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        asset_status = st.radio("Asset Status *", ASSET_STATUS_OPTIONS, horizontal=True)
    with c2:
        location_status = st.radio("Location Status *", LOCATION_STATUS_OPTIONS, horizontal=True)
    with c3:
        other_status = st.radio("Other Status *", OTHER_STATUS_OPTIONS, horizontal=True)

    verified_by = st.session_state.get("auth_full_name", "")
    st.caption(f"Verified by: **{verified_by}**")

    if st.button("📋 Save Verification", use_container_width=True, type="primary"):
        vdf = load_df("Verifications", VERIFICATION_COLUMNS)
        verification_id = next_id(vdf, "Verification ID", "VER")
        append_row("Verifications", VERIFICATION_COLUMNS, {
            "Verification ID": verification_id, "Item Code": item_code,
            "Verification Date": today_str(), "Asset Status": asset_status,
            "Location Status": location_status, "Other Status": other_status,
            "Verified By": verified_by, "Office at Verification": row["Office"],
            "Location at Verification": row["Location"],
        })
        if asset_status == "Missing" or other_status == "Damaged":
            update_row_by_key("Assets", ASSET_COLUMNS, "Item Code", item_code, {
                "Condition": "Damaged" if other_status == "Damaged" else row["Condition"],
                "Last Updated": now_str(),
            })
        st.success(f"✅ Verification recorded for **{item_code}**.")
        st.rerun()


# ============================================================================
# SECTION 4: ASSET DISPOSAL
# ============================================================================

def page_asset_disposal():
    st.header("🗑️ Asset Disposal")
    tab_view, tab_new = st.tabs(["📄 Disposal Assets View", "➕ New Asset Disposal Request"])

    ddf = load_df("DisposalRequests", DISPOSAL_COLUMNS)
    adf = load_df("Assets", ASSET_COLUMNS)

    with tab_new:
        if adf.empty:
            st.info("No assets registered yet.")
        else:
            item_code, row = asset_lookup_block(adf, "disp")
            if item_code is not None:
                st.divider()
                reason = st.text_area("Reason for Disposal *", height=80)
                requested_by = st.session_state.get("auth_full_name", "")
                st.caption(f"Requested by: **{requested_by}**")
                if st.button("📨 Send Disposal Request", type="primary", use_container_width=True):
                    if not reason.strip():
                        st.error("Please provide a reason for disposal.")
                    else:
                        request_id = next_id(ddf, "Request ID", "DIS")
                        append_row("DisposalRequests", DISPOSAL_COLUMNS, {
                            "Request ID": request_id, "Item Code": item_code,
                            "Requested By": requested_by, "Request Date": now_str(),
                            "Reason": reason, "Status": "Pending",
                            "Reviewed By": "", "Review Date": "", "Review Notes": "",
                        })
                        st.success(f"✅ Disposal request **{request_id}** sent for **{item_code}**. "
                                   f"Admin has been notified.")
                        st.rerun()

    with tab_view:
        st.subheader("Pending Requests")
        pending = ddf[ddf["Status"] == "Pending"] if not ddf.empty else ddf
        if pending.empty:
            st.caption("No pending disposal requests.")
        else:
            st.dataframe(pending, use_container_width=True, hide_index=True)

            is_admin = st.session_state.get("auth_role") == "Admin"
            if is_admin:
                st.markdown("**Review a Request**")
                req_id = st.selectbox("Request ID", ["(select)"] + pending["Request ID"].tolist())
                if req_id != "(select)":
                    reviewer = st.session_state.get("auth_full_name", "")
                    st.caption(f"Reviewed by: **{reviewer}**")
                    notes = st.text_input("Review Notes")
                    c1, c2 = st.columns(2)
                    if c1.button("✅ Approve & Dispose", type="primary", use_container_width=True):
                        update_row_by_key("DisposalRequests", DISPOSAL_COLUMNS, "Request ID", req_id, {
                            "Status": "Approved", "Reviewed By": reviewer,
                            "Review Date": now_str(), "Review Notes": notes,
                        })
                        target_code = pending[pending["Request ID"] == req_id]["Item Code"].iloc[0]
                        update_row_by_key("Assets", ASSET_COLUMNS, "Item Code", target_code, {
                            "Status": "Disposed", "Last Updated": now_str(),
                        })
                        st.success(f"Request {req_id} approved — asset marked as Disposed.")
                        st.rerun()
                    if c2.button("❌ Reject", use_container_width=True):
                        update_row_by_key("DisposalRequests", DISPOSAL_COLUMNS, "Request ID", req_id, {
                            "Status": "Rejected", "Reviewed By": reviewer,
                            "Review Date": now_str(), "Review Notes": notes,
                        })
                        st.warning(f"Request {req_id} rejected.")
                        st.rerun()
            else:
                st.caption("🔒 Only the Admin account can approve or reject requests.")

        st.subheader("Disposed Assets")
        disposed = adf[adf["Status"] == "Disposed"] if not adf.empty else adf
        if disposed.empty:
            st.caption("No disposed assets yet.")
        else:
            st.dataframe(disposed[ASSET_COLUMNS], use_container_width=True, hide_index=True)

        with st.expander("📜 Full Disposal Request History"):
            st.dataframe(ddf, use_container_width=True, hide_index=True)


# ============================================================================
# SECTION 5: SEARCH & FILTERS
# ============================================================================

def page_search_filters():
    st.header("🔎 Search & Filters")
    df = load_df("Assets", ASSET_COLUMNS)

    if df.empty:
        st.info("No assets registered yet.")
        return

    display_cols = ["Office", "Location", "Sub Location", "Item Code", "Item Name",
                     "Main Category", "Sub Category", "Description", "Brand/Model",
                     "Serial No", "Date of Purchase", "Purchased From", "User",
                     "Condition", "Amount"]

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        f_office = st.multiselect("Office Wise", sorted(df["Office"].unique()))
    with c2:
        f_category = st.multiselect("Main Category Wise", sorted(df["Main Category"].unique()))
    with c3:
        f_location = st.multiselect("Location Wise", sorted(df["Location"].unique()))
    with c4:
        f_user = st.multiselect("User Wise", sorted(df["User"].unique()))
    with c5:
        f_condition = st.multiselect("Condition Wise", sorted(df["Condition"].unique()))

    search_text = st.text_input("Free-text search (Item Code, Item Name, Serial No, Description...)")

    filtered = df.copy()
    if f_office:
        filtered = filtered[filtered["Office"].isin(f_office)]
    if f_category:
        filtered = filtered[filtered["Main Category"].isin(f_category)]
    if f_location:
        filtered = filtered[filtered["Location"].isin(f_location)]
    if f_user:
        filtered = filtered[filtered["User"].isin(f_user)]
    if f_condition:
        filtered = filtered[filtered["Condition"].isin(f_condition)]
    if search_text:
        mask = filtered.apply(lambda r: search_text.lower() in " ".join(map(str, r.values)).lower(), axis=1)
        filtered = filtered[mask]

    st.caption(f"Showing {len(filtered)} of {len(df)} assets"
               + (f"  |  Total value: LKR {pd.to_numeric(filtered['Amount'], errors='coerce').sum():,.2f}"
                  if not filtered.empty else ""))
    st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)

    csv = filtered[display_cols].to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download filtered results (CSV)", csv, "asset_register_filtered.csv", "text/csv")


# ============================================================================
# SIDEBAR / LOGIN
# ============================================================================

def sidebar():
    st.sidebar.title("🏢 KMN Fixed Assets")

    role = st.session_state.get("auth_role", "")
    badge = "👑 Admin" if role == "Admin" else "👤 User"
    st.sidebar.success(f"{badge}: **{st.session_state.get('auth_full_name', '')}**")
    if st.session_state.get("auth_office"):
        st.sidebar.caption(f"Office: {st.session_state['auth_office']}")
    if st.sidebar.button("🚪 Log Out"):
        for k in ("auth_username", "auth_full_name", "auth_role", "auth_office"):
            st.session_state.pop(k, None)
        st.rerun()

    st.sidebar.divider()
    page = st.sidebar.radio(
        "Navigate",
        ["1. Asset Register", "2. Asset Transfers", "3. Annual Asset Verification",
         "4. Asset Disposal", "5. Search & Filters"],
    )
    st.sidebar.divider()
    if st.sidebar.button("🔄 Refresh Data"):
        clear_caches()
        st.rerun()

    return page


# ============================================================================
# MAIN
# ============================================================================

def main():
    st.set_page_config(page_title="Fixed Asset Management System - KMN",
                        page_icon="🏢", layout="wide")

    try:
        get_spreadsheet()
    except Exception as e:
        st.error(
            "⚠️ Could not connect to the Google Sheet. Make sure `gcp_service_account` is set "
            "in `.streamlit/secrets.toml` and the sheet is shared with the service account's "
            "email address as an Editor.\n\nDetails: " + str(e)
        )
        st.stop()

    require_login()

    page = sidebar()

    st.title("Fixed Asset Management System")
    st.caption("KMN | Chilaw & Palavi Offices")

    if page.startswith("1"):
        page_asset_register()
    elif page.startswith("2"):
        page_asset_transfers()
    elif page.startswith("3"):
        page_annual_verification()
    elif page.startswith("4"):
        page_asset_disposal()
    elif page.startswith("5"):
        page_search_filters()


if __name__ == "__main__":
    main()
