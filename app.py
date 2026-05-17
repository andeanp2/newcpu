import streamlit as st
import duckdb
import pandas as pd
import pytz
from datetime import datetime
import plotly.express as px

# 1. KONFIGURASI UTAMA & WAKTU (WIB)
wib_tz = pytz.timezone('Asia/Jakarta')
st.set_page_config(page_title="Dynamic Traceability System", layout="wide")

st.title("🔄 Reverse Traceability System - MotherDuck Integration")
current_wib = datetime.now(wib_tz).strftime("%Y-%m-%d %H:%M:%S WIB")
st.caption(f"Server Sinkronisasi: Online | Zona Waktu: {current_wib}")

# 2. KONEKSI KE DATABASE MOTHERDUCK
@st.cache_resource
def get_md_connection():
    """Membuka koneksi permanen ke MotherDuck menggunakan Token dari Secrets"""
    try:
        # Mengambil token dari sistem rahasia Streamlit
        md_token = st.secrets["MOTHERDUCK_TOKEN"]
        # Mengoneksikan ke database cloud (secara default bernama 'my_db' di MotherDuck)
        conn = duckdb.connect(f"md:newc?token={md_token}")
        return conn
    except Exception as e:
        st.error(f"Gagal terhubung ke MotherDuck Cloud: {e}")
        st.info("Pastikan Anda telah mengatur 'MOTHERDUCK_TOKEN' di Advanced Settings Streamlit.")
        return None

conn = get_md_connection()

# 3. INISIALISASI SKEMA TABEL DATABASE (DDL)
def init_db_tables(connection):
    """Membuat tabel otomatis jika belum terbentuk di MotherDuck Instance"""
    if connection:
        # Tabel 1: Master Barang
        connection.execute("""
            CREATE TABLE IF NOT EXISTS master_barang (
                nama VARCHAR PRIMARY KEY,
                kategori VARCHAR,
                std_pemanasan INT
            );
        """)
        # Tabel 2: Master Pemasok (Data SK)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS master_pemasok (
                nkv VARCHAR PRIMARY KEY,
                nama_pemasok VARCHAR,
                alamat VARCHAR,
                gram_awal DOUBLE,
                kg_awal DOUBLE
            );
        """)
        # Tabel 3: Log Transaksi Harian (Date)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS log_produksi (
                batch_id VARCHAR PRIMARY KEY,
                tanggal_terima DATE,
                tanggal_cabut DATE,
                tanggal_cetak DATE,
                tanggal_eksport DATE,
                susut_cabut DOUBLE,
                susut_cetak DOUBLE
            );
        """)
        
        # --- PERBAIKAN DI SINI ---
        # 1. Buat sequence generator terlebih dahulu jika belum ada
        connection.execute("CREATE SEQUENCE IF NOT EXISTS seq_id_ccp;")
        
        # 2. Gunakan BIGINT dengan DEFAULT nextval() untuk auto-increment
        connection.execute("""
            CREATE TABLE IF NOT EXISTS log_ccp (
                id_ccp BIGINT DEFAULT nextval('seq_id_ccp'),
                batch_id VARCHAR,
                tanggal_ccp DATE,
                jenis_item VARCHAR,
                gramasi DOUBLE,
                jumlah_pcs INT
            );
        """)

if conn:
    init_db_tables(conn)

# 4. ANTARMUKA MENU (TABS)
tab1, tab2, tab3 = st.tabs(["🔍 Traceability Engine", "📝 Dynamic Input Forms", "📊 Analitik & Monitoring"])

# --- TAB 1: ENGINE PELACAKAN (READ-ONLY VIA SQL JOINS) ---
with tab1:
    st.header("Mesin Pelacakan Keterlacakan Mundur")
    search_query = st.text_input("Masukkan Kode Batch Produk Jadi untuk Traceback:", placeholder="Contoh: 2030.01125.1")
    
    if search_query and conn:
        # Melakukan kueri relasional lintas tabel langsung di Cloud MotherDuck
        sql_query = f"""
            SELECT 
                c.batch_id AS "Nomor Batch",
                c.tanggal_ccp AS "Tanggal CCP",
                c.jenis_item AS "Jenis Komoditas",
                c.gramasi AS "Massa CCP (Gr)",
                c.jumlah_pcs AS "Kuantitas (Pcs)",
                p.nama_pemasok AS "Nama Pemasok Asal",
                p.alamat AS "Lokasi Asal RUM",
                r.tanggal_terima AS "Waktu Penerimaan",
                r.susut_cetak AS "Persentase Susut Produksi"
            FROM log_ccp c
            LEFT JOIN log_produksi r ON c.batch_id = r.batch_id
            LEFT JOIN master_pemasok p ON p.nkv IS NOT NULL 
            WHERE c.batch_id LIKE '%{search_query}%'
            ORDER BY c.tanggal_ccp DESC
        """
        try:
            res_df = conn.execute(sql_query).df()
            if not res_df.empty:
                st.success("Rantai pasokan berhasil dilacak mundur dari database cloud!")
                
                # Metrik Ringkasan Utama
                m1, m2, m3 = st.columns(3)
                m1.metric("Pemasok Asal", str(res_df["Nama Pemasok Asal"].iloc[0]))
                m2.metric("Wilayah Sumber", str(res_df["Lokasi Asal RUM"].iloc[0]))
                m3.metric("Rerata Gramasi", f"{res_df['Massa CCP (Gr)'].mean():.2f} gr")
                
                st.dataframe(res_df, use_container_width=True)
            else:
                st.warning("Data kueri batch tersebut tidak ditemukan di repositori data MotherDuck.")
        except Exception as query_err:
            st.error(f"Kesalahan eksekusi SQL: {query_err}")

# --- TAB 2: INPUT FORMS DINAMIS (WRITE PATH TO DATABASE) ---
with tab2:
    st.header("Manajemen Pengisian Data Real-Time")
    form_select = st.selectbox("Pilih Formulir Input Data Baru:", 
                               ["1. Master Komoditas Barang", "2. Registrasi Pemasok (Data SK)", "3. Alur Log Produksi & Susut", "4. Pencatatan Kualitas CCP 2"])
    
    if conn:
        # FORM 1: MASTER BARANG
        if form_select == "1. Master Komoditas Barang":
            with st.form("form_barang", clear_on_submit=True):
                st.subheader("Form Input Master Barang")
                f_nama = st.text_input("Nama Item (Contoh: VIP-S1)")
                f_kat = st.selectbox("Kategori", ["M", "V", "T", "P"])
                f_std = st.number_input("Standar Pemanasan (Detik/Nilai)", min_value=0, value=750)
                
                if st.form_submit_button("Simpan Data Komoditas"):
                    if f_nama:
                        conn.execute("INSERT OR REPLACE INTO master_barang VALUES (?, ?, ?)", [f_nama, f_kat, f_std])
                        st.success(f"Item {f_nama} berhasil direkam ke MotherDuck Cloud Database.")
                    else:
                        st.error("Nama item tidak boleh kosong.")

        # FORM 2: MASTER PEMASOK
        elif form_select == "2. Registrasi Pemasok (Data SK)":
            with st.form("form_pemasok", clear_on_submit=True):
                st.subheader("Form Registrasi Pemasok Baru")
                f_nkv = st.text_input("Nomor Kontrol Veteriner / NKV")
                f_nama_p = st.text_input("Nama Pemasok / Rumah Walet")
                f_alamat = st.text_input("Alamat Lokasi (Contoh: Sumbawa, NTB)")
                col_b1, col_b2 = st.columns(2)
                f_gram = col_b1.number_input("Berat Masuk Awal (Gram)", min_value=0.0)
                f_kg = col_b2.number_input("Berat Masuk Awal (Kg)", min_value=0.0)
                
                if st.form_submit_button("Simpan Data Pemasok"):
                    if f_nkv and f_nama_p:
                        conn.execute("INSERT OR REPLACE INTO master_pemasok VALUES (?, ?, ?, ?, ?)", [f_nkv, f_nama_p, f_alamat, f_gram, f_kg])
                        st.success(f"Pemasok {f_nama_p} berhasil didaftarkan di sistem database cloud.")
                    else:
                        st.error("NKV dan Nama Pemasok wajib diisi.")

        # FORM 3: LOG PRODUKSI
        elif form_select == "3. Alur Log Produksi & Susut":
            with st.form("form_produksi", clear_on_submit=True):
                st.subheader("Form Alur Pemrosesan Batch Produksi")
                f_batch = st.text_input("ID Batch Produksi Utama", placeholder="Contoh: 2002.01125.1")
                
                c1, c2, c3, c4 = st.columns(4)
                t_terima = c1.date_input("Tanggal Terima")
                t_cabut = c2.date_input("Tanggal Cabut")
                t_cetak = c3.date_input("Tanggal Cetak")
                t_eksport = c4.date_input("Tanggal Eksport")
                
                cs1, cs2 = st.columns(2)
                s_cabut = cs1.number_input("Persentase Susut Cabut (%)", min_value=0.0, max_value=100.0, step=0.01)
                s_cetak = cs2.number_input("Persentase Susut Cetak (%)", min_value=0.0, max_value=100.0, step=0.01)
                
                if st.form_submit_button("Rekam Alur Log Batch"):
                    if f_batch:
                        conn.execute("""
                            INSERT OR REPLACE INTO log_produksi VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, [f_batch, t_terima, t_cabut, t_cetak, t_eksport, s_cabut, s_cetak])
                        st.success(f"Log alur pemrosesan batch {f_batch} berhasil diverifikasi.")
                    else:
                        st.error("ID Batch Utama wajib ditentukan.")

        # FORM 4: LOG QUALITY CONTROL / CCP 2
        elif form_select == "4. Pencatatan Kualitas CCP 2":
            with st.form("form_ccp", clear_on_submit=True):
                st.subheader("Form Input Pengukuran Critical Control Point (CCP 2)")
                f_batch_ccp = st.text_input("ID Batch Target")
                f_tgl_ccp = st.date_input("Tanggal Pengukuran CCP")
                f_jenis = st.text_input("Jenis / Sub-Item Kategori (Contoh: MK1)")
                
                col_ccp1, col_ccp2 = st.columns(2)
                f_grm_ccp = col_ccp1.number_input("Berat Riil Hasil Uji (Gram)", min_value=0.0)
                f_pcs_ccp = col_ccp2.number_input("Total Kuantitas Output (Pcs)", min_value=0)
                
                if st.form_submit_button("Simpan Hasil Uji CCP"):
                    if f_batch_ccp:
                        conn.execute("""
                            INSERT INTO log_ccp (batch_id, tanggal_ccp, jenis_item, gramasi, jumlah_pcs) 
                            VALUES (?, ?, ?, ?, ?)
                        """, [f_batch_ccp, f_tgl_ccp, f_jenis, f_grm_ccp, f_pcs_ccp])
                        st.success(f"Data sampling QC CCP untuk batch {f_batch_ccp} tersimpan di MotherDuck.")
                    else:
                        st.error("ID Batch target wajib ditentukan.")

# --- TAB 3: MONITORING & DATA AUDIT ---
with tab3:
    st.header("Arsip Audit Data Cloud")
    if conn:
        inspect_select = st.selectbox("Pilih Tabel untuk Ditinjau Langsung dari MotherDuck:", 
                                      ["Daftar Seluruh Komoditas", "Daftar Pemasok Teregistrasi", "Log Riwayat Transaksi Produksi", "Log CCP Komplet"])
        
        mapping = {
            "Daftar Seluruh Komoditas": "SELECT * FROM master_barang LIMIT 100",
            "Daftar Pemasok Teregistrasi": "SELECT * FROM master_pemasok LIMIT 100",
            "Log Riwayat Transaksi Produksi": "SELECT * FROM log_produksi LIMIT 100",
            "Log CCP Komplet": "SELECT * FROM log_ccp LIMIT 100"
        }
        
        audit_df = conn.execute(mapping[inspect_select]).df()
        st.dataframe(audit_df, use_container_width=True)
        
        # Visualisasi Ringkas jika ada data di tabel CCP
        if inspect_select == "Log CCP Komplet" and not audit_df.empty:
            st.subheader("Visualisasi Sebaran Gramasi Hasil Input")
            fig_bar = px.box(audit_df, x="jenis_item", y="gramasi", points="all", title="Distribusi Kualitas Gramasi per Jenis Komoditas")
            st.plotly_chart(fig_bar, use_container_width=True)