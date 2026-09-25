# Fixed Asset Management System - KMN

A Streamlit app backed by Google Sheets, covering:
1. Asset Register
2. Asset Transfers
3. Annual Asset Verification
4. Asset Disposal (request + admin approval)
5. Search & Filters

## Data model (auto-created as tabs in your Google Sheet)
- **Users** — accounts: Username, salted+hashed Password, Full Name, Role (Admin/User), Office
- **Assets** — the master register (one row per asset, with a `Status` of Active/Disposed)
- **Transfers** — audit log of every transfer
- **Verifications** — audit log of every annual verification
- **DisposalRequests** — disposal request queue + approval trail

## Accounts
The app supports **exactly 1 Admin + 3 Users**, each with their own username and password:
- On first launch, open the app, go to the **Create Account** tab and register the Admin first.
- Each of the 3 staff members then registers their own User account the same way (Role: User).
- Once all 4 slots are filled, the Create Account tab shows only the Log In tab is usable —
  ask the Admin if a password needs resetting (currently done by editing the `Users` tab
  directly in the Google Sheet, since there's no self-service reset yet).
- Only the **Admin** role can approve/reject Asset Disposal requests; **Users** can do everything
  else (Register, Transfer, Verify, Search, and submit Disposal requests).
- Passwords are stored as salted SHA-256 hashes, never in plain text.

The app creates these tabs automatically the first time it runs, with headers.

## One-time setup

1. **Create a Google Service Account**
   - Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials.
   - Create a Service Account, then create a JSON key for it.
   - Enable the **Google Sheets API** and **Google Drive API** for the project.

2. **Share the spreadsheet**
   - Open your sheet: https://docs.google.com/spreadsheets/d/1f6qisix5WFGTxLHNQL4xwvX1vp__U7DYkuJHRy72QS0/edit
   - Click Share, and add the service account's `client_email` (from the JSON key) as an **Editor**.

3. **Configure secrets**
   - Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`.
   - Paste in the values from your service account JSON key under `[gcp_service_account]`.

4. **Install & run**
   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   ```

## Notes on design choices
- **Item Code** auto-suggests as `KMN/<OfficeCode>/<CategoryCode>/<Number>` (e.g. `KMN/CH/FF/001`)
  based on Office + Main Category, but stays editable in case you want to override it.
- **Location** and **Main Category** use a "recommend as you type" selector: once a value has
  been entered once, it appears in the dropdown for next time, with an "➕ Add New..." option
  for anything new.
- **Office** selection in Asset Register remembers your last choice for the session.
- **Login is required** for every section; the currently logged-in user's name is auto-attached
  to whatever they save (Entered By, Transferred By, Verified By, Requested By, Reviewed By) —
  no one can type someone else's name in. Only the Admin account can approve/reject Asset
  Disposal requests, mirroring the "Asset Officers request → Admin disposes" workflow.
- Disposing an asset sets its `Status` to `Disposed` in the Assets sheet — it then drops out of
  Transfers/Verification/Disposal item pickers automatically, and shows up in the
  "Disposed Assets" view.
