# SSSS Dashboard - User Guide

## 🌟 Welcome to SSSS Dashboard

**SSSS** = **S**ense.i **S**oftware **S**amsung and **S**K hynix

Your web-based tool information management dashboard with full editing capabilities.

---

## 🚀 Quick Start

1. **Open Browser**: Navigate to `http://10.173.135.202:8060`
2. **View Data**: See all tool information in color-coded table
3. **Edit Cells**: Click any cell to edit content
4. **Save Changes**: Click "💾 Save Changes" button
5. **Export Data**: Click "📥 Export CSV" to download

---

## 📖 Features Guide

### 1️⃣ Viewing Data

#### Color Coding
- **Fab Column**: Each fab (R3, M15, R4, etc.) has unique background color
- **PM Columns**: Each module name has unique background color
- **Easy Identification**: Quickly spot patterns and groupings

#### Scrolling
- **Horizontal Scroll**: Use mouse wheel + Shift to scroll left/right
- **Vertical Scroll**: Standard mouse wheel scrolling
- **Large Tables**: Smooth performance with current 45 rows

---

### 2️⃣ Editing Data

#### Edit a Cell
```
1. Click the cell you want to edit
2. Cell highlights with yellow background
3. Type or paste new content
4. Cell shows yellow + orange border (modified)
5. Click outside cell to finish editing
```

#### Visual Indicators
- **Unmodified**: Normal background color
- **Editable (hover)**: Light yellow on hover
- **Modified**: Yellow background + orange left border
- **Deleted Row**: Gray with strikethrough text

#### Supported Content
- ✅ Text (letters, numbers, symbols)
- ✅ Special characters (#, -, ., etc.)
- ✅ Empty cells (delete all text)
- ✅ Copy/paste from Excel or other sources

---

### 3️⃣ Saving Changes

#### Save Process
```
1. Make edits to one or more cells
2. Modified cells turn yellow with orange border
3. Click "💾 Save Changes" button (top left)
4. Green success message appears
5. Changes saved to CSV file
6. Modified indicators cleared
```

#### What Gets Saved
- ✅ All cell edits (modified cells)
- ✅ New rows added
- ✅ Deleted rows removed
- ✅ Column order preserved
- ✅ Color coding maintained

#### Success Message
```
✅ Changes saved successfully!
```

#### Error Message
```
❌ Error saving changes: [error details]
```

---

### 4️⃣ Adding Rows

#### Add New Row
```
1. Click "➕ Add Row" button (top)
2. Empty row appears at bottom of table
3. Click cells to enter data
4. Fill in all required columns
5. Click "💾 Save Changes"
```

#### Tips
- Start with leftmost columns (Import, Fab, ToolID)
- Copy existing row data for consistency
- Leave empty if column not applicable
- Save frequently when adding multiple rows

---

### 5️⃣ Deleting Rows

#### Delete Process
```
1. Find row to delete
2. Click "🗑️ Delete" button on right
3. Confirm deletion in popup dialog
4. Row gets strikethrough (not deleted yet!)
5. Click "💾 Save Changes" to permanently remove
```

#### Confirmation Dialog
```
Are you sure you want to delete this row?
[Cancel] [OK]
```

#### Undo Deletion
- Before saving: Refresh page (F5) to restore
- After saving: No undo! Use CSV backup to restore

---

### 6️⃣ Exporting Data

#### Export Current Table
```
1. Click "📥 Export CSV" button
2. File downloads automatically
3. Filename: SKH_tool_information_2025-11-17.csv
4. Open in Excel or text editor
```

#### Export Includes
- ✅ All current table data
- ✅ Unsaved changes (what you see)
- ✅ Newly added rows
- ✅ Excludes deleted rows
- ✅ Proper CSV format

#### Use Cases
- **Backup**: Before making major changes
- **Sharing**: Send data to colleagues
- **Analysis**: Import into Excel/Python
- **Archive**: Regular data snapshots

---

## 🎯 Common Workflows

### Workflow 1: Update Single Tool
```
1. Find tool row (use Ctrl+F to search)
2. Click cell to edit (e.g., "Current SW")
3. Type new value
4. Click "💾 Save Changes"
5. Done! ✅
```

### Workflow 2: Add New Tool
```
1. Click "➕ Add Row"
2. Fill in Import: ConfigOptionsAll
3. Fill in Fab: P4H
4. Fill in ToolID: ELP42A4
5. Fill remaining columns
6. Click "💾 Save Changes"
7. New tool added! ✅
```

### Workflow 3: Bulk Update
```
1. Edit multiple cells across rows
2. Yellow indicators show modified cells
3. Review changes visually
4. Click "📥 Export CSV" (backup)
5. Click "💾 Save Changes"
6. All changes saved! ✅
```

### Workflow 4: Delete Obsolete Tools
```
1. Click "🗑️ Delete" on each obsolete row
2. Rows show strikethrough
3. Click "📥 Export CSV" (backup with deletions)
4. Click "💾 Save Changes"
5. Rows permanently removed! ✅
```

---

## ⚠️ Important Notes

### Before Making Changes
- ✅ **Export CSV backup** (in case of mistakes)
- ✅ **Coordinate with team** (avoid conflicts)
- ✅ **Test on small changes** first

### While Editing
- ✅ **Yellow indicators** show what changed
- ✅ **Save frequently** (don't lose work)
- ✅ **Check spelling** (no auto-correct)

### After Saving
- ✅ **Verify changes** in table
- ✅ **Export updated CSV** (new backup)
- ✅ **Notify team** of significant updates

---

## 🔧 Troubleshooting

### Problem: Can't Edit Cells
**Solution**: Refresh page (F5) and try again

### Problem: Changes Not Saving
**Check**:
1. Yellow indicators visible? (changes detected)
2. Error message? (check console F12)
3. File permissions? (CSV writable)
4. Server running? (green status indicator)

### Problem: Export Not Working
**Try**:
1. Disable popup blocker
2. Check Downloads folder
3. Try different browser (Chrome, Edge)

### Problem: Row Deleted by Accident
**Before Save**: Refresh page (F5) to restore
**After Save**: Use previous CSV backup to restore

### Problem: Multiple Users Editing
**Issue**: Last save wins (overwrites others)
**Solution**: 
1. Communicate who's editing
2. Work on different rows
3. Save frequently
4. Export backups often

---

## 💡 Pro Tips

### Tip 1: Keyboard Shortcuts
- `Ctrl + F`: Find text in page
- `Tab`: Move to next cell
- `Enter`: New line within cell
- `F5`: Refresh page (discard unsaved)
- `Ctrl + C/V`: Copy/paste

### Tip 2: Excel Integration
1. Export CSV from dashboard
2. Open in Excel
3. Make bulk edits in Excel
4. Save as CSV
5. Copy data back to dashboard
6. Save changes

### Tip 3: Regular Backups
```powershell
# Automated daily backup (server)
$date = Get-Date -Format "yyyyMMdd"
Copy-Item "C:\FlaskDashboard\app\data\SKH_tool_information_fixed.csv" `
          "D:\Backups\SKH_data_$date.csv"
```

### Tip 4: Data Validation
- Check ToolID format before saving
- Verify Fab names match standards
- Ensure MAC addresses valid format
- Confirm software versions accurate

---

## 📞 Getting Help

### Self-Service
1. Check this User Guide
2. Review UPDATE_LOG.md for changes
3. Read README.md for setup info
4. Check browser console (F12) for errors

### IT Support
- Server issues: Contact IT help desk
- Network access: Check firewall settings
- Performance: Monitor server resources
- Bugs: Report with screenshots

---

## 📊 Data Columns Reference

| Column | Description | Example |
|--------|-------------|---------|
| Import | Configuration type | ConfigOptionsAll |
| Fab | Fabrication facility | R3, M15, P4H, NRD-K |
| ToolID | Tool identifier | ELPC61, 5ELVD701 |
| FID | Factory ID number | 227148-0469 |
| Platform | Platform version | #SydneyA1V6 |
| Current SW | Current software version | 1.8.4-SP30-HF20-Release |
| Current Patch | Current patch version | 5.1, P4, P7 |
| Target SW | Target software version | 1.8.4-SP33-HF3-Release |
| Target Patch | Target patch version | 1, 2 |
| MAC Address | Network MAC address | C4-00-AD-D1-88-02 |
| EDA | EDA installation | #Not_Installed |
| DDS_HSD | DDS/HSD status | #Not_Installed |
| LAA | LAA archiver | #LamArchiver |
| PM01-PM10 | Process module configs | #AkaraBL, #VantexB |
| PM95-PM96 | Additional PM slots | #ICS_S_Beta |
| Save | Save indicator | (empty) |

---

**Dashboard**: http://10.173.135.202:8060  
**Version**: 2.0  
**Last Updated**: November 17, 2025
