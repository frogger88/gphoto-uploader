# Google Photos Transfer Application
# This script provides a GUI to select local photo folders, create corresponding albums in Google Photos,
# upload the photos, and track processed folders to avoid duplicates.

import os
import json
import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

# Google API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Scopes required for uploading and managing albums
SCOPES = [
    "https://www.googleapis.com/auth/photoslibrary.appendonly",
    "https://www.googleapis.com/auth/photoslibrary.readonly",
    "https://www.googleapis.com/auth/photoslibrary.sharing",
]

# Path to the OAuth client secret JSON you obtain from Google Cloud Console.
# The user must place this file in the project root.
CLIENT_SECRETS_FILE = "client_secret.json"

# File that stores detailed transfer logs
TRANSFER_LOG_FILE = "transfer_log.txt"

# SQLite database for tracking transfer state
DB_FILE = "transfer_state.db"

# ---------------------------------------------------------------------------
# Helper functions for Logging
# ---------------------------------------------------------------------------

def log_message(message: str):
    """Log a message with a timestamp to both console and log file."""
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {message}"
    print(formatted_msg)
    with open(TRANSFER_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(formatted_msg + "\n")

# ---------------------------------------------------------------------------
# Database Management
# ---------------------------------------------------------------------------

class TransferDB:
    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS folders (
                    path TEXT PRIMARY KEY,
                    album_id TEXT,
                    status TEXT DEFAULT 'pending'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    folder_path TEXT,
                    status TEXT DEFAULT 'pending',
                    FOREIGN KEY(folder_path) REFERENCES folders(path)
                )
            """)
            conn.commit()

    def get_folder_resumption_data(self, folder_path: str):
        """Returns (album_id, status) for a folder."""
        folder_path = Path(folder_path).as_posix()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT album_id, status FROM folders WHERE path = ?", (folder_path,))
            return cursor.fetchone()

    def set_folder_album(self, folder_path: str, album_id: str):
        folder_path = Path(folder_path).as_posix()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO folders (path, album_id) VALUES (?, ?)
                ON CONFLICT(path) DO UPDATE SET album_id = excluded.album_id
            """, (folder_path, album_id))
            conn.commit()

    def set_folder_status(self, folder_path: str, status: str):
        folder_path = Path(folder_path).as_posix()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE folders SET status = ? WHERE path = ?", (status, folder_path))
            conn.commit()

    def is_file_uploaded(self, file_path: str) -> bool:
        file_path = Path(file_path).as_posix()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM files WHERE path = ? AND status = 'uploaded'", (file_path,))
            return cursor.fetchone() is not None

    def mark_file_uploaded(self, file_path: str, folder_path: str):
        file_path = Path(file_path).as_posix()
        folder_path = Path(folder_path).as_posix()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO files (path, folder_path, status) VALUES (?, ?, 'uploaded')
                ON CONFLICT(path) DO UPDATE SET status = 'uploaded'
            """, (file_path, folder_path))
            conn.commit()

# ---------------------------------------------------------------------------
# Google API imports (continued)
# ---------------------------------------------------------------------------

def authenticate() -> any:
    """Authenticate the user and return a Google Photos service object.
    The function uses the OAuth flow and stores the credentials in a token.json file.
    """
    token_path = Path("token.json")
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    # If there are no (valid) credentials, run the flow.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        token_path.write_text(creds.to_json())
    service = build("photoslibrary", "v1", credentials=creds, static_discovery=False)
    return service


def create_album(service, title: str) -> str:
    """Create an album with the given title.
    Returns the albumId.
    """
    request_body = {"album": {"title": title}}
    response = service.albums().create(body=request_body).execute()
    return response.get("id")


def upload_bytes(service, file_path: str) -> str:
    """Upload raw bytes of a file to Google Photos.
    Returns the upload token (valid for 1 day).
    """
    file_name = os.path.basename(file_path)
    # Determine MIME type – simple heuristic based on extension
    mime_type = "image/jpeg"
    if file_path.lower().endswith('.png'):
        mime_type = "image/png"
    elif file_path.lower().endswith('.gif'):
        mime_type = "image/gif"
    elif file_path.lower().endswith('.mp4'):
        mime_type = "video/mp4"
    # Read file bytes
    with open(file_path, "rb") as f:
        data = f.read()
    upload_url = "https://photoslibrary.googleapis.com/v1/uploads"
    headers = {
        "Authorization": f"Bearer {service._http.credentials.token}",
        "Content-type": "application/octet-stream",
        "X-Goog-Upload-File-Name": file_name,
        "X-Goog-Upload-Protocol": "raw",
    }
    # Use the underlying Http request object from the service
    http = service._http
    response, content = http.request(upload_url, method="POST", body=data, headers=headers)
    if response.status != 200:
        raise RuntimeError(f"Upload failed for {file_path}: {content}")
    upload_token = content.decode("utf-8")
    return upload_token


def batch_create_media_items(service, upload_tokens: list, album_id: str = None) -> list:
    """Create media items from upload tokens.
    Returns a list of created media item IDs.
    """
    new_media_items = []
    for token in upload_tokens:
        item = {"simpleMediaItem": {"uploadToken": token}}
        new_media_items.append(item)
    body = {"newMediaItems": new_media_items}
    if album_id:
        body["albumId"] = album_id
    response = service.mediaItems().batchCreate(body=body).execute()
    created = []
    for result in response.get("newMediaItemResults", []):
        if "mediaItem" in result:
            created.append(result["mediaItem"]["id"])
    return created


def add_media_items_to_album(service, album_id: str, media_item_ids: list):
    """Add existing media items to an album.
    The API call fails if any ID is invalid.
    """
    body = {"mediaItemIds": media_item_ids}
    service.albums().batchAddMediaItems(albumId=album_id, body=body).execute()

# ---------------------------------------------------------------------------
# Migration helper
# ---------------------------------------------------------------------------

def migrate_json_to_db(db: TransferDB):
    json_path = Path("processed_folders.json")
    if json_path.exists():
        log_message("Found legacy processed_folders.json. Migrating to database...")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for folder_path, status in data.items():
                    if status == "processed":
                        db.set_folder_status(folder_path, "processed")
            # Rename legacy file to avoid re-migration
            json_path.rename("processed_folders.json.bak")
            log_message("Migration complete. Legacy file renamed to .bak")
        except Exception as e:
            log_message(f"Migration error: {e}")

# ---------------------------------------------------------------------------
# GUI implementation
# ---------------------------------------------------------------------------
class TransferApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Google Photos Transfer")
        self.geometry("800x600")
        self.service = None
        self.db = TransferDB()
        migrate_json_to_db(self.db)
        self.selected_folders = []
        self.source_parent = ""
        self.create_widgets()

    def create_widgets(self):
        # Configure style
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=25)
        
        main_container = ttk.Frame(self)
        main_container.pack(fill="both", expand=True, padx=20, pady=20)

        # 1. Source Selection Frame
        source_frame = ttk.LabelFrame(main_container, text="1. Select Source Parent Directory (e.g., Takeout folder)")
        source_frame.pack(fill="x", pady=(0, 10))
        
        source_inner = ttk.Frame(source_frame)
        source_inner.pack(fill="x", padx=10, pady=10)
        
        self.source_label = ttk.Label(source_inner, text="No source selected", foreground="gray")
        self.source_label.pack(side="left", fill="x", expand=True)
        
        ttk.Button(source_inner, text="Browse", command=self.select_source).pack(side="right")

        # 2. Folder List Frame (PanedWindow to separate Checklist and Queue)
        paned = ttk.PanedWindow(main_container, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True)

        # Checklist side
        checklist_outer = ttk.LabelFrame(paned, text="2. Available Sub-folders")
        paned.add(checklist_outer, weight=3)
        
        checklist_inner = ttk.Frame(checklist_outer)
        checklist_inner.pack(fill="both", expand=True, padx=5, pady=5)

        # Treeview for checklist
        columns = ("Selection", "Folder Name", "Status")
        self.tree = ttk.Treeview(checklist_inner, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("Selection", text="[ ]")
        self.tree.heading("Folder Name", text="Folder Name")
        self.tree.heading("Status", text="Status")
        
        self.tree.column("Selection", width=40, anchor="center")
        self.tree.column("Folder Name", width=250)
        self.tree.column("Status", width=100, anchor="center")
        
        scrollbar = ttk.Scrollbar(checklist_inner, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.tree.bind("<ButtonRelease-1>", self.on_tree_click)

        # Checklist Controls
        checklist_buttons = ttk.Frame(checklist_outer)
        checklist_buttons.pack(fill="x", padx=5, pady=5)
        ttk.Button(checklist_buttons, text="Select All Ready", command=self.select_all_ready).pack(side="left", padx=2)
        ttk.Button(checklist_buttons, text="Add Selected to Queue", command=self.add_selected_to_queue).pack(side="right", padx=2)

        # Queue side
        queue_outer = ttk.LabelFrame(paned, text="3. Transfer Queue")
        paned.add(queue_outer, weight=2)
        
        queue_inner = ttk.Frame(queue_outer)
        queue_inner.pack(fill="both", expand=True, padx=5, pady=5)

        self.queue_listbox = tk.Listbox(queue_inner, selectmode=tk.MULTIPLE)
        self.queue_listbox.pack(side="left", fill="both", expand=True)
        
        q_scrollbar = ttk.Scrollbar(queue_inner, orient="vertical", command=self.queue_listbox.yview)
        self.queue_listbox.configure(yscrollcommand=q_scrollbar.set)
        q_scrollbar.pack(side="right", fill="y")

        # Footer with progress bar
        footer = ttk.Frame(main_container)
        footer.pack(fill="x", pady=(10, 0))
        
        ttk.Button(footer, text="Remove from Queue", command=self.remove_from_queue).pack(side="left")
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(footer, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=10)
        
        ttk.Button(footer, text="Start Transfer", command=self.start_transfer).pack(side="right")

    def select_source(self):
        folder = filedialog.askdirectory()
        if folder:
            self.source_parent = folder
            self.source_label.config(text=folder, foreground="black")
            self.refresh_folder_list()

    def refresh_folder_list(self):
        # Clear existing
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        if not self.source_parent:
            return

        # Scan subdirectories
        try:
            subdirs = [d for d in os.listdir(self.source_parent) if os.path.isdir(os.path.join(self.source_parent, d))]
            subdirs.sort()
            
            for d in subdirs:
                # Normalize path to posix style for consistent matching
                full_path = Path(self.source_parent) / d
                full_path_str = full_path.as_posix()
                
                db_data = self.db.get_folder_resumption_data(full_path_str)
                status = db_data[1] if db_data else "Ready"
                # If DB has a record, it might be 'pending' or 'processed'
                display_status = "Uploaded" if status == "processed" else "Ready"
                icon = "[ ]" if display_status == "Ready" else "[x]"
                
                self.tree.insert("", tk.END, values=(icon, d, display_status), tags=(display_status,))
            
            self.tree.tag_configure("Uploaded", foreground="gray")
            self.tree.tag_configure("Ready", foreground="black")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to list subdirectories: {e}")

    def on_tree_click(self, event):
        item_id = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not item_id:
            return
            
        values = list(self.tree.item(item_id, "values"))
        status = values[2]
        
        # Toggle checkbox only if not already uploaded
        if column == "#1":
            if status == "Uploaded":
                messagebox.showinfo("Info", "This folder has already been uploaded.")
                return
                
            current = values[0]
            values[0] = "[V]" if current == "[ ]" else "[ ]"
            self.tree.item(item_id, values=values)

    def select_all_ready(self):
        for item_id in self.tree.get_children():
            values = list(self.tree.item(item_id, "values"))
            if values[2] == "Ready":
                values[0] = "[V]"
                self.tree.item(item_id, values=values)

    def add_selected_to_queue(self):
        added_count = 0
        for item_id in self.tree.get_children():
            values = self.tree.item(item_id, "values")
            if values[0] == "[V]":
                folder_name = values[1]
                full_path = Path(self.source_parent) / folder_name
                full_path_str = full_path.as_posix()
                
                if full_path_str not in self.selected_folders:
                    self.selected_folders.append(full_path_str)
                    self.queue_listbox.insert(tk.END, folder_name)
                    added_count += 1
                
                # Reset checkbox after adding
                new_values = list(values)
                new_values[0] = "[ ]"
                self.tree.item(item_id, values=new_values)
        
        if added_count == 0:
            messagebox.showinfo("Info", "No new folders were selected to add.")

    def remove_from_queue(self):
        selected = list(self.queue_listbox.curselection())
        for idx in reversed(selected):
            # We need to map back to the path. Since queue_listbox only stores names, 
            # we should maintain a synchronized list or store paths directly.
            # Let's use self.selected_folders as the source of truth.
            folder_path = self.selected_folders[idx]
            self.selected_folders.pop(idx)
            self.queue_listbox.delete(idx)

    def start_transfer(self):
        if not self.selected_folders:
            messagebox.showwarning("Warning", "No folders selected.")
            return
        try:
            self.service = authenticate()
        except Exception as e:
            messagebox.showerror("Error", f"Authentication failed: {e}")
            return
        
        total = len(self.selected_folders)
        for i, folder in enumerate(list(self.selected_folders)):
            success = self.process_folder(folder)
            
            # Update progress
            self.progress_var.set(((i + 1) / total) * 100)
            self.update_idletasks()
            
            if success:
                # Remove from queue only if truly successful
                self.selected_folders.pop(0)
                self.queue_listbox.delete(0)
            else:
                log_message(f"Stopping transfer loop due to error in folder: {folder}")
                messagebox.showwarning("Transfer Paused", 
                    f"The transfer was paused due to an error (likely API quota or connection issue).\n\n"
                    "Progress has been saved. You can try resuming the remaining folders later.")
                break
            
        # Refresh checklist to show new statuses
        self.refresh_folder_list()
        self.progress_var.set(0)
        
        messagebox.showinfo("Done", "Processing complete. Please check the log for details.")

    def process_folder(self, folder_path: str) -> bool:
        """Process a folder and return True if successful, False if a fatal error occurred."""
        # Ensure path is posix normalized
        folder_path = Path(folder_path).as_posix()
        folder_name = os.path.basename(folder_path)
        
        # Check database for existing status
        resumption_data = self.db.get_folder_resumption_data(folder_path)
        existing_album_id = None
        if resumption_data:
            existing_album_id, status = resumption_data
            if status == "processed":
                log_message(f"Skipping already processed folder: {folder_path}")
                return True
        
        log_message(f"Starting transfer for folder: {folder_path}")
        
        # Determine if this is an album folder
        is_album = not folder_name.lower().startswith("photos from")
        album_id = existing_album_id
        
        if is_album and not album_id:
            try:
                album_id = create_album(self.service, folder_name)
                self.db.set_folder_album(folder_path, album_id)
                log_message(f"Created album '{folder_name}' with id {album_id}")
            except Exception as e:
                error_msg = str(e)
                log_message(f"Error: Failed to create album '{folder_name}': {error_msg}")
                if "quota" in error_msg.lower() or "429" in error_msg:
                    return False
                return False # Treat album creation failure as fatal for this folder
        elif is_album and album_id:
            log_message(f"Resuming folder '{folder_name}' using existing album ID: {album_id}")
        else:
            log_message(f"Folder '{folder_name}' will be uploaded to library without a dedicated album.")

        # Gather image files
        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        all_files = []
        for root, _, files in os.walk(folder_path):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in image_extensions:
                    all_files.append(os.path.join(root, f))
        
        if not all_files:
            log_message(f"No image files found in {folder_path}")
            self.db.set_folder_status(folder_path, "processed")
            return True
            
        # Filter out already uploaded files
        files_to_upload = [f for f in all_files if not self.db.is_file_uploaded(f)]
        skipped_count = len(all_files) - len(files_to_upload)
        
        if skipped_count > 0:
            log_message(f"Skipping {skipped_count} already uploaded files.")
            
        if not files_to_upload:
            log_message(f"All files in {folder_name} already uploaded. Marking folder as processed.")
            self.db.set_folder_status(folder_path, "processed")
            return True

        log_message(f"Found {len(files_to_upload)} new files to upload.")

        # Upload files in batches
        BATCH_SIZE = 10 
        for i in range(0, len(files_to_upload), BATCH_SIZE):
            batch = files_to_upload[i : i + BATCH_SIZE]
            upload_tokens = []
            current_batch_paths = []
            
            for file_path in batch:
                try:
                    token = upload_bytes(self.service, file_path)
                    upload_tokens.append(token)
                    current_batch_paths.append(file_path)
                    log_message(f"Successfully uploaded: {file_path}")
                except Exception as e:
                    error_msg = str(e)
                    log_message(f"Failed to upload {file_path}: {error_msg}")
                    # If quota error, stop immediately
                    if "quota" in error_msg.lower() or "429" in error_msg:
                        return False
                    # Otherwise continue to next file in batch
            
            if upload_tokens:
                try:
                    batch_create_media_items(self.service, upload_tokens, album_id=album_id)
                    for path in current_batch_paths:
                        self.db.mark_file_uploaded(path, folder_path)
                except Exception as e:
                    error_msg = str(e)
                    log_message(f"Error: Failed to create media items for batch in '{folder_name}': {error_msg}")
                    if "quota" in error_msg.lower() or "429" in error_msg:
                        return False
        
        # Mark folder as processed only if we reached the end
        self.db.set_folder_status(folder_path, "processed")
        log_message(f"Completed processing folder: {folder_path}")
        return True

if __name__ == "__main__":
    app = TransferApp()
    app.mainloop()
