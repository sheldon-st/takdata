# Packages — Frontend Build Brief

## What this feature is

A simple file sharing section where users can upload data packages (`.zip` files containing certs and metadata) and others can download them. This is a new section in the existing TAK Manager frontend app.

---

## API reference

All endpoints are under `/api/v1/packages`.

---

### List packages

```
GET /api/v1/packages
```

Returns an array of package objects, sorted newest first.

**Response `200`:**

```json
[
  {
    "package_id": "a1b2c3d4e5f60718",
    "filename": "my-certs.zip",
    "size": 204800
  }
]
```

- `package_id` — opaque 16-char hex string used to reference the file
- `filename` — the original filename as uploaded
- `size` — file size in bytes

---

### Upload a package

```
POST /api/v1/packages
Content-Type: multipart/form-data
```

Field name: `file` — must be a `.zip` file, max 100 MB.

**Response `201`:**

```json
{
  "package_id": "a1b2c3d4e5f60718",
  "filename": "my-certs.zip",
  "size": 204800
}
```

**Error responses:**

- `400` — not a `.zip` file, or empty file
- `413` — file exceeds 100 MB

---

### Download a package

```
GET /api/v1/packages/{package_id}
```

Returns the `.zip` file as a binary download with `Content-Disposition: attachment` and `Content-Type: application/zip`. The browser will prompt a file save with the original filename.

**Error responses:**

- `404` — package not found

---

### Delete a package

```
DELETE /api/v1/packages/{package_id}
```

**Response `204` — no body.**

**Error responses:**

- `404` — package not found

---

## What to implement

### Packages page / section

A single view (add this to the sidebar) that contains:

1. **Package list**
   - Table or card list showing all uploaded packages
   - Columns/fields: filename, size (formatted as KB/MB), a download button, a delete button
   - Empty state message when no packages have been uploaded yet
   - List should refresh after a successful upload or delete

2. **Upload area**
   - A file input (or drag-and-drop zone) that only accepts `.zip` files
   - An upload button that submits the selected file
   - Show a loading/progress state while uploading
   - Show a success confirmation when done (then refresh the list)
   - Show an inline error message if the upload fails (e.g. wrong file type, too large)

3. **Download**
   - Clicking the download button for a package triggers `GET /api/v1/packages/{package_id}` — the browser handles the file save automatically. No custom download logic needed; a plain `<a href="...">` or `window.location` pointing to the endpoint is sufficient.

4. **Delete**
   - Clicking delete on a package calls `DELETE /api/v1/packages/{package_id}`
   - Ask for confirmation before deleting (simple confirm dialog or inline confirm step)
   - Remove the item from the list on success

---

## Notes

- Files are only `.zip` — no need to handle other types
- Max upload size is 100 MB — show a clear error if exceeded
- No pagination needed for now; the list is expected to be short
- No authentication on these endpoints — the app is expected to run on a private network
