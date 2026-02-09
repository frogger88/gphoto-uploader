# Setup and Usage Instructions

Follow these steps to set up the Google Photos Transfer tool for your own use.

## 1. Google Cloud Project Setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project.
3. Search for "Google Photos Library API" and enable it for your project.
4. Go to the "Credentials" tab.
5. Click "Create Credentials" > "OAuth client ID".
6. Select "Desktop app" as the application type.
7. Download the JSON credentials file and rename it to `client_secret.json`.
8. Place the `client_secret.json` file in the same directory as the script.

### 1.1. ⚠️ CRITICAL: Add Test Users

Since your Google Cloud project is likely in "Testing" mode:
1. Go to the "OAuth consent screen" tab in the Google Cloud Console.
2. Find the "Test users" section.
3. Click "+ ADD USERS" and enter the Gmail address of the account you plan to upload *to*.
4. **Without this step, you will see a '403 Access Blocked' error when trying to log in.**

## 2. Installation

1. Ensure you have Python installed.
2. It is recommended to use a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## 3. Usage

1. Run the application:
   ```bash
   python google_photos_transfer_app.py
   ```
2. **Select Source:** Click "Browse" and select the **parent directory** that contains your photo folders (e.g., the `Google Photos` folder from a Takeout zip).
3. **Queue Folders:** 
   - The tool will scan all sub-folders.
   - Folders already uploaded appear as "[x] Uploaded" (tracked in `transfer_state.db`).
   - Select the folders you want to upload and click "Add Selected to Queue".
4. **Authenticate:** Click "Start Transfer". A browser window will open; log in to the **destination** account.
5. **Monitor:** Watch the progress bar. If interrupted, simply restart the app—it will remember where it left off.

## Note on Google Takeout

Ensure your Google Takeout archive is extracted. The tool works best when you select the folder containing individual album sub-folders (e.g., `Takeout/Google Photos/`).

## 💡 Pro Tip: Identity and Ownership

The Google Photos API restricts certain actions (like renaming albums or deleting photos) to the "app that created them." 

- **Identity:** Your identity is tied to your **Google Cloud Project ID**. 
- **Consistency:** As long as you use the same Google Cloud Project, you can generate new `client_secret.json` files or use different computers, and Google will still recognize "you" as the owner of the photos and albums uploaded by this tool.
- **Avoid:** Do not delete your Google Cloud Project or move to a new one if you plan to manage these same photos/albums programmatically in the future.
