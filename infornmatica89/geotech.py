import os
from flask import Flask, render_template, jsonify, request, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename
import requests
import pymysql

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'chiave_segreta_geotech_2026')

# Configurazione Cartella Upload e Limiti di Caricamento
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ==========================================
# CONNESSIONE DATABASE MYSQL (CON VARIABILI D'AMBIENTE)
# ==========================================
def connetti_a_mysql():
    """
    Funzione per connettersi al database MySQL remoto.
    Prende i dati dalle variabili d'ambiente per sicurezza.
    """
    try:
        # Se i dati non sono configurati sul server cloud, usa i fallback di test locali
        host_db = os.environ.get('DB_HOST', 'mysql-49fbfd2-antony-60d4.h.aivencloud.com')
        port_db = int(os.environ.get('DB_PORT', 26057))
        user_db = os.environ.get('DB_USER', 'avnadmin')
        password_db = os.environ.get('DB_PASSWORD', 'AVNS_hANinbx3h7rgy2trxG3') # <-- Ricordati di cambiarla su Aiven!
        name_db = os.environ.get('DB_NAME', 'defaultdb')

        connection = pymysql.connect(
            host=host_db,
            port=port_db,
            user=user_db,
            password=password_db,
            database=name_db,
            cursorclass=pymysql.cursors.DictCursor,
            ssl={'ssl': {}}  # Aiven richiede la cifratura SSL obbligatoria
        )
        return connection
    except Exception as e:
        print(f"Errore di connessione al database MySQL: {e}")
        return None

# ==========================================
# ROTTE FLASK (ONLINE VIA DB)
# ==========================================

# Gestione della Favicon nativa da cartella static
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

# Home Page
@app.route('/')
def home():
    username = session.get('username', 'Ospite')
    ruolo = session.get('ruolo', 'guest')
    nazione = session.get('nazione', 'N/D')
    return render_template('geotech.html', username=username, ruolo=ruolo, nazione=nazione)

# Upload File (Solo Admin)
@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if session.get('ruolo') != 'admin': 
        return "Accesso Negato", 403
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            return render_template('upload.html', successo=True, nome_file=filename)
    return render_template('upload.html', successo=False)

# Area Riservata Antony
@app.route('/fsl_antony')
def fsl_antony():
    if session.get('username') != 'antony': 
        return "Accesso Negato", 403
    return render_template('fsl_antony.html')

# Registrazione Utente sul Database Online
@app.route('/registrazione', methods=['GET', 'POST'])
def registrazione():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        nazione = request.form['nazione']
        
        db = connetti_a_mysql()
        if db is None:
            return "Errore di connessione al database", 500
            
        try:
            with db.cursor() as cursor:
                # Verifica se l'username esiste già nel DB
                cursor.execute("SELECT username FROM utenti WHERE username = %s", (username,))
                if cursor.fetchone():
                    return "Esistente", 400
                
                # Inserisce il nuovo utente
                sql = "INSERT INTO utenti (username, password, ruolo, nazione) VALUES (%s, %s, 'user', %s)"
                cursor.execute(sql, (username, password, nazione))
                db.commit()
                return redirect(url_for('login'))
        finally:
            db.close()
            
    return render_template('registrazione.html')

# Login Utente verificato sul Database Online
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        db = connetti_a_mysql()
        if db is None:
            return "Errore di connessione al database", 500
            
        try:
            with db.cursor() as cursor:
                # Cerca l'utente nel database
                sql = "SELECT * FROM utenti WHERE username = %s"
                cursor.execute(sql, (username,))
                utente = cursor.fetchone()
                
                # Controllo credenziali
                if utente and utente['password'] == password:
                    session['username'] = utente['username']
                    session['ruolo'] = utente['ruolo']
                    session['nazione'] = utente['nazione']
                    return redirect(url_for('home'))
                return "Errore credenziali", 401
        finally:
            db.close()
            
    return render_template('login.html')

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# API Recupero Dati Paese (Integrazione DB Aiven + API Esterna RestCountries)
@app.route('/api/paese/<nome_paese>')
def api_paese(nome_paese):
    if session.get('ruolo', 'guest') == 'guest': 
        return jsonify({"errore_permesso": True})
    
    mappa_nomi = {
        "United States": "USA", "China": "China", "Russia": "Russia", "Italy": "Italy", "Japan": "Japan",
        "Germany": "Germany", "United Kingdom": "United Kingdom", "India": "India", "Brazil": "Brazil",
        "Australia": "Australia", "South Africa": "South Africa", "Saudi Arabia": "Saudi Arabia", "France": "France",
        "Canada": "Canada", "South Korea": "South Korea", "Israel": "Israel", "Spain": "Spain", "Ukraine": "Ukraine",
        "Egypt": "Egypt", "Nigeria": "Nigeria", "Turkey": "Turkey", "Argentina": "Argentina", "Mexico": "Mexico",
        "Indonesia": "Indonesia", "Singapore": "Singapore", "Netherlands": "Netherlands", "Switzerland": "Switzerland",
        "Sweden": "Sweden", "Poland": "Poland", "United Arab Emirates": "United Arab Emirates"
    }
    
    chiave_interna = mappa_nomi.get(nome_paese, nome_paese)
    info_base = {"nome": nome_paese, "capitale": "Rilevata", "bandiera": "", "popolazione": "Mappata"}
    
    try:
        # Richiesta HTTP a servizio esterno RestCountries per completare i dati geografici
        risposta = requests.get(f"https://restcountries.com/v3.1/name/{nome_paese}?fullText=true", verify=False, timeout=1.5)
        if risposta.status_code == 200:
            dati = risposta.json()[0]
            info_base["capitale"] = dati.get('capital', ['N/D'])[0]
            info_base["bandiera"] = dati.get('flags', {}).get('png', '')
            info_base["popolazione"] = f"{dati.get('population', 0):,}"
    except Exception: 
        pass

    # Inizializziamo i valori di fallback se il paese non è censito nel DB
    info_geotech = {"leader": "N/D", "economia": "N/D", "cybersecurity": "N/D", "aziende": "N/D"}
    commenti_paese = []
    
    db = connetti_a_mysql()
    if db:
        try:
            with db.cursor() as cursor:
                # 1. Recupera i dati del dossier Geotech dal database online
                sql_geo = "SELECT leader, alleanze, economia, tecnologia, cybersecurity, aziende FROM dati_geotech WHERE paese = %s"
                cursor.execute(sql_geo, (chiave_interna,))
                risultato_geo = cursor.fetchone()
                if risultato_geo:
                    info_geotech = risultato_geo
                    if info_geotech.get('alleanze'):
                        info_geotech['alleanze'] = [a.strip() for a in info_geotech['alleanze'].split(',')]
                    else:
                        info_geotech['alleanze'] = []

                # 2. Recupera i commenti associati a questo paese dal database online
                sql_comm = "SELECT autore, testo FROM commenti WHERE paese = %s ORDER BY id DESC"
                cursor.execute(sql_comm, (chiave_interna,))
                commenti_paese = cursor.fetchall()
        finally:
            db.close()
    
    return jsonify({**info_base, **info_geotech, "commenti": commenti_paese, "errore_permesso": False})

# API per aggiungere un commento sul Database Online
@app.route('/api/commento', methods=['POST'])
def aggiungi_commento():
    if 'username' not in session:
        return "Non autorizzato", 401
        
    data = request.json
    paese = data.get('paese')
    testo = data.get('testo')
    
    if paese and testo:
        db = connetti_a_mysql()
        if db:
            try:
                with db.cursor() as cursor:
                    sql = "INSERT INTO commenti (paese, autore, testo) VALUES (%s, %s, %s)"
                    cursor.execute(sql, (paese, session['username'], testo))
                    db.commit()
                return jsonify({"stato": "successo"})
            finally:
                db.close()
    return "Errore", 400

# API per modificare i dati del Dossier Geotech sul Database (Solo Admin)
@app.route('/api/modifica', methods=['POST'])
def modifica_dossier():
    if session.get('ruolo') != 'admin': 
        return "Vietato", 403
        
    data = request.json
    paese = data.get('paese')
    campo = data.get('campo')
    valore = data.get('valore')
    
    # Lista di controllo per evitare SQL Injection sui nomi delle colonne dinamiche
    campi_ammessi = ['leader', 'alleanze', 'economia', 'tecnologia', 'cybersecurity', 'aziende']
    if campo not in campi_ammessi:
        return "Campo non valido", 400
    
    db = connetti_a_mysql()
    if db:
        try:
            with db.cursor() as cursor:
                # Aggiorna dinamicamente il campo verificato per il paese selezionato
                sql = f"UPDATE dati_geotech SET {campo} = %s WHERE paese = %s"
                cursor.execute(sql, (valore, paese))
                db.commit()
                return jsonify({"stato": "modificato"})
        finally:
            db.close()
            
    return "Errore connessione database", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)