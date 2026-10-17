# Medicine Expiry Alert System (MedAlert Enterprise)

An enterprise-grade, full-stack pharmaceutical inventory and regulatory compliance system featuring **First-Expired, First-Out (FEFO) dispensing**, **Live Camera Barcode/QR Scanning**, **Certified Quarantine & Destruction Logging**, **Official PDF Inspection Reports**, **Desktop Push Notifications**, **Multi-Role RBAC**, and **Dynamic Expiry Countdown Alerts**.

---

## 🚀 Newly Added Features

### 1. 📷 Live Camera Barcode & QR Code Scanner
- Real-time scanner powered by `html5-qrcode` accessible from the top navigation, Dashboard, and Add Medicine form.
- Point any device webcam or mobile camera at medicine barcodes (EAN-13, Code-128, UPC) or QR codes.
- **One-Click Auto-Fill:** Instantly populates the barcode and batch fields on the Add Medicine form.
- **Instant FEFO Lookup:** Scanning a barcode on the dashboard immediately pulls up the drug and identifies the earliest expiring batch.

### 2. 💊 FEFO (First-Expired, First-Out) Dispensing Assistant
- **Guaranteed Expiry Protection:** Automatically sorts all in-stock batches of a drug by `expiry_date ASC`.
- **Recommended Batch Flag:** Highlights the optimal batch to dispense first to minimize waste.
- **Critical Safety Guard:** Blocks or displays severe warnings if staff attempt to dispense an expired batch, prompting immediate quarantine.
- **Dispensing Transaction Audit Log (`/dispense_history`):** Tracks quantity, patient/ward destination, and dispensing staff member.

### 3. 🗑️ Certified Quarantine & Destruction Log
- Regulatory compliance workflow for condemning expired, damaged, recalled, or temperature-abused stock.
- Automatically deducts or purges quarantined stock from active dispensing channels.
- Logs the *Reason, Disposal Method (Incineration, Encapsulation, Vendor Return), Authorized Officer, and Witness*.
- **Printable Certificate of Destruction (`/disposal_certificate/<id>`):** Official digital audit certificate with verification numbers for hospital inspectors.

### 4. 📑 Official PDF Inspection Report Generator
- Generates high-resolution, printable PDF inspection reports using Python's `reportlab`.
- Formatted with medical letterheads, audit timestamps, safety rating gauges, critical expired lists, and formal Chief Pharmacist and Regulatory Inspector sign-off signature blocks.
- One-click download available on the Dashboard, Inventory, and Reports tabs (`/export_pdf`).

### 5. 🔔 Browser Desktop Push Notifications
- Uses the HTML5 Notifications API to push native OS/browser desktop notification toasts.
- Alerts pharmacists even when the MedAlert tab is minimized or in the background whenever medicines enter the critical 7-day window or expire.
- Quick activation bell toggle located in the top navigation bar.

---

## 👥 Role-Based Access Control (RBAC)
- **Administrator (`admin`)**: Full hospital-wide stock monitoring, user management, role adjustments, global inventory auditing.
- **Pharmacist / Manager (`pharmacist`)**: Full stock management, FEFO dispensing, quarantine authorization, picture OCR, report export.
- **Clinical Staff / Nurse (`staff`)**: Operational dispensing, batch logging, stock updates, tap-to-alert (deletion restricted).
- **Doctor / Auditor (`viewer`)**: Read-only clinical lookup, batch verification, audit reports.

---

## 🛠️ Technology Stack
- **Frontend:** HTML5, CSS3, JavaScript (ES6+), Bootstrap 5, FontAwesome 6, Chart.js, HTML5-QRCode
- **Backend:** Python 3 (Flask)
- **Database:** MySQL (automatic schema migration)
- **PDF Engine:** ReportLab
- **Audio & Vision:** Web Speech API, PyTesseract, Pillow

---

## 💻 Setup Instructions for Windows (VS Code)

### 1. Prerequisites
- [Python 3.10+](https://www.python.org/downloads/)
- [MySQL Server](https://dev.mysql.com/downloads/mysql/) running locally.
- (Optional) [Tesseract-OCR](https://github.com/UB-Mannheim/tesseract/wiki) for picture scanning.

### 2. Application Setup
1. Open the project folder in VS Code:
   ```cmd
   cd D:\OneDrive\Desktop\medicine-expiry-alert
   ```
2. Activate your virtual environment:
   ```cmd
   venv\Scripts\activate
   ```
3. Install the updated requirements (including `reportlab`):
   ```cmd
   pip install -r requirements.txt
   ```
4. Verify your `.env` file credentials:
   ```env
   DB_HOST=localhost
   DB_USER=root
   DB_PASSWORD=your_password
   DB_NAME=medicine_db
   ```

### 3. Run the Application
```cmd
python app.py
```
Open [http://127.0.0.1:5000/](http://127.0.0.1:5000/) in your browser.

---

## 🧪 Testing the New Features
1. **Live Barcode Scanner:** Click the **"Scan"** button in the top navbar or on Add Medicine to test camera barcode detection.
2. **Desktop Push Notifications:** Click the **Bell (🔔)** icon in the top navbar and click "Allow" to enable desktop alerts.
3. **FEFO Dispense:** Click **"FEFO Dispense"** in the navbar, pick any drug, and observe the priority batch recommendations and safety checks.
4. **Quarantine & Disposal:** On any expired medicine in the dashboard or inventory, click **"Quarantine"** to log the destruction protocol and print the Certificate.
5. **PDF Inspection Report:** Click **"PDF Audit Report"** on the dashboard to generate and download the printable audit sheet.
