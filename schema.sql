CREATE DATABASE IF NOT EXISTS medicine_db;
USE medicine_db;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'pharmacist',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS medicines (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(150) NOT NULL,
    category VARCHAR(100) NOT NULL,
    batch_number VARCHAR(100) NOT NULL,
    barcode VARCHAR(100),
    manufacturer VARCHAR(150),
    quantity INT NOT NULL,
    manufacturing_date DATE,
    expiry_date DATE NOT NULL,
    purchase_date DATE,
    supplier_name VARCHAR(150),
    minimum_stock INT DEFAULT 10,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS disposals (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    medicine_name VARCHAR(150) NOT NULL,
    category VARCHAR(100),
    batch_number VARCHAR(100) NOT NULL,
    quantity INT NOT NULL,
    expiry_date DATE,
    reason VARCHAR(100) NOT NULL,
    disposal_method VARCHAR(100) NOT NULL,
    witness_name VARCHAR(150),
    notes TEXT,
    disposed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dispenses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    medicine_id INT,
    medicine_name VARCHAR(150) NOT NULL,
    batch_number VARCHAR(100) NOT NULL,
    quantity INT NOT NULL,
    patient_or_dest VARCHAR(150),
    dispensed_by INT NOT NULL,
    dispensed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dispensed_by) REFERENCES users(id) ON DELETE CASCADE
);
