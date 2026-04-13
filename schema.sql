-- ============================================================
--  TranspoBot — Base de données MySQL
--  Projet GLSi L3 — ESP/UCAD
-- ============================================================

CREATE DATABASE IF NOT EXISTS transpobot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE transpobot;

-- Véhicules
CREATE TABLE vehicules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    immatriculation VARCHAR(20) NOT NULL UNIQUE,
    type ENUM('bus','minibus','taxi') NOT NULL,
    capacite INT NOT NULL,
    statut ENUM('actif','maintenance','hors_service') DEFAULT 'actif',
    kilometrage INT DEFAULT 0,
    date_acquisition DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chauffeurs
CREATE TABLE chauffeurs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nom VARCHAR(100) NOT NULL,
    prenom VARCHAR(100) NOT NULL,
    telephone VARCHAR(20),
    numero_permis VARCHAR(30) UNIQUE NOT NULL,
    categorie_permis VARCHAR(5),
    disponibilite BOOLEAN DEFAULT TRUE,
    vehicule_id INT,
    date_embauche DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vehicule_id) REFERENCES vehicules(id)
);

-- Lignes / trajets types
CREATE TABLE lignes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(10) NOT NULL UNIQUE,
    nom VARCHAR(100),
    origine VARCHAR(100) NOT NULL,
    destination VARCHAR(100) NOT NULL,
    distance_km DECIMAL(6,2),
    duree_minutes INT
);

-- Tarifs
CREATE TABLE tarifs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ligne_id INT NOT NULL,
    type_client ENUM('normal','etudiant','senior') DEFAULT 'normal',
    prix DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (ligne_id) REFERENCES lignes(id)
);

-- Trajets effectués
CREATE TABLE trajets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ligne_id INT NOT NULL,
    chauffeur_id INT NOT NULL,
    vehicule_id INT NOT NULL,
    date_heure_depart DATETIME NOT NULL,
    date_heure_arrivee DATETIME,
    statut ENUM('planifie','en_cours','termine','annule') DEFAULT 'planifie',
    nb_passagers INT DEFAULT 0,
    recette DECIMAL(10,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ligne_id) REFERENCES lignes(id),
    FOREIGN KEY (chauffeur_id) REFERENCES chauffeurs(id),
    FOREIGN KEY (vehicule_id) REFERENCES vehicules(id)
);

-- Incidents
CREATE TABLE incidents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    trajet_id INT NOT NULL,
    type ENUM('panne','accident','retard','autre') NOT NULL,
    description TEXT,
    gravite ENUM('faible','moyen','grave') DEFAULT 'faible',
    date_incident DATETIME NOT NULL,
    resolu BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trajet_id) REFERENCES trajets(id)
);

-- ============================================================
--  Données de test
-- ============================================================
INSERT INTO vehicules (immatriculation, type, capacite, statut, kilometrage, date_acquisition) VALUES
('DK-1234-AB', 'bus', 60, 'actif', 45000, '2021-03-15'),
('DK-5678-CD', 'minibus', 25, 'actif', 32000, '2022-06-01'),
('DK-9012-EF', 'bus', 60, 'maintenance', 78000, '2019-11-20'),
('DK-3456-GH', 'taxi', 5, 'actif', 120000, '2020-01-10'),
('DK-7890-IJ', 'minibus', 25, 'actif', 15000, '2023-09-05');

INSERT INTO chauffeurs (nom, prenom, telephone, numero_permis, categorie_permis, vehicule_id, date_embauche) VALUES
('DIOP', 'Mamadou', '+221771234567', 'P-2019-001', 'D', 1, '2019-04-01'),
('FALL', 'Ibrahima', '+221772345678', 'P-2020-002', 'D', 2, '2020-07-15'),
('NDIAYE', 'Fatou', '+221773456789', 'P-2021-003', 'B', 4, '2021-02-01'),
('SECK', 'Ousmane', '+221774567890', 'P-2022-004', 'D', 5, '2022-10-20'),
('BA', 'Aminata', '+221775678901', 'P-2023-005', 'D', NULL, '2023-01-10');

INSERT INTO lignes (code, nom, origine, destination, distance_km, duree_minutes) VALUES
('L1', 'Ligne Dakar-Thiès', 'Dakar', 'Thiès', 70.5, 90),
('L2', 'Ligne Dakar-Mbour', 'Dakar', 'Mbour', 82.0, 120),
('L3', 'Ligne Centre-Banlieue', 'Plateau', 'Pikine', 15.0, 45),
('L4', 'Ligne Aéroport', 'Centre-ville', 'AIBD', 45.0, 60);

INSERT INTO tarifs (ligne_id, type_client, prix) VALUES
(1, 'normal', 2500), (1, 'etudiant', 1500), (1, 'senior', 1800),
(2, 'normal', 3000), (2, 'etudiant', 1800),
(3, 'normal', 500),  (3, 'etudiant', 300),
(4, 'normal', 5000), (4, 'etudiant', 3000);

INSERT INTO trajets (ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut, nb_passagers, recette) VALUES
(1, 1, 1, '2026-03-01 06:00:00', '2026-03-01 07:30:00', 'termine', 55, 137500),
(1, 2, 2, '2026-03-01 08:00:00', '2026-03-01 09:30:00', 'termine', 20, 50000),
(2, 3, 4, '2026-03-02 07:00:00', '2026-03-02 09:00:00', 'termine', 4, 12000),
(3, 4, 5, '2026-03-05 07:30:00', '2026-03-05 08:15:00', 'termine', 22, 11000),
(1, 1, 1, '2026-03-10 06:00:00', '2026-03-10 07:30:00', 'termine', 58, 145000),
(4, 2, 2, '2026-03-12 09:00:00', '2026-03-12 10:00:00', 'termine', 18, 90000),
(1, 5, 1, '2026-03-20 06:00:00', NULL, 'en_cours', 45, 112500),
(1, 1, 1, '2026-04-11 06:00:00', '2026-04-11 07:30:00', 'termine', 52, 130000),
(2, 2, 2, '2026-04-11 08:00:00', '2026-04-11 10:00:00', 'termine', 22, 66000),
(3, 3, 4, '2026-04-10 07:30:00', '2026-04-10 08:15:00', 'termine', 18, 9000),
(4, 4, 5, '2026-04-10 09:00:00', '2026-04-10 10:00:00', 'termine', 38, 190000),
(1, 5, 1, '2026-04-09 06:00:00', '2026-04-09 07:30:00', 'termine', 60, 150000),
(1, 1, 1, '2026-04-08 06:00:00', '2026-04-08 07:30:00', 'termine', 48, 120000),
(2, 2, 2, '2026-04-08 08:00:00', '2026-04-08 10:00:00', 'termine', 20, 60000),
(3, 4, 5, '2026-04-07 07:30:00', '2026-04-07 08:15:00', 'termine', 25, 12500),
(1, 3, 1, '2026-04-07 06:00:00', '2026-04-07 07:30:00', 'termine', 55, 137500),
(4, 5, 2, '2026-04-06 09:00:00', '2026-04-06 10:00:00', 'termine', 42, 210000),
(1, 1, 1, '2026-04-04 06:00:00', '2026-04-04 07:30:00', 'termine', 58, 145000),
(2, 2, 2, '2026-04-02 08:00:00', '2026-04-02 10:00:00', 'termine', 24, 72000),
(3, 3, 4, '2026-03-31 07:30:00', '2026-03-31 08:15:00', 'termine', 15, 7500),
(1, 4, 5, '2026-03-28 06:00:00', '2026-03-28 07:30:00', 'termine', 50, 125000),
(4, 1, 1, '2026-03-25 09:00:00', '2026-03-25 10:00:00', 'termine', 35, 175000),
(2, 5, 2, '2026-03-23 08:00:00', NULL,                  'annule',   0, 0),
(1, 2, 1, '2026-03-21 06:00:00', '2026-03-21 07:30:00', 'termine', 61, 152500),
(3, 3, 4, '2026-03-18 07:30:00', '2026-03-18 08:15:00', 'termine', 20, 10000),
(1, 1, 1, '2026-04-12 06:00:00', NULL,                  'en_cours', 45, 0),
(2, 4, 5, '2026-04-12 08:00:00', NULL,                  'en_cours', 18, 0);


INSERT INTO incidents (trajet_id, type, description, gravite, date_incident, resolu) VALUES
(2, 'retard', 'Embouteillage au centre-ville', 'faible', '2026-03-01 08:45:00', TRUE),
(3, 'panne', 'Crevaison pneu avant droit', 'moyen', '2026-03-02 07:30:00', TRUE),
(6, 'accident', 'Accrochage léger au rond-point', 'grave', '2026-03-12 09:20:00', FALSE),
(8,  'retard',   'Embouteillage Dakar-Plateau matin',  'faible', '2026-04-11 08:45:00', TRUE),
(9,  'panne',    'Surchauffe moteur, arrêt 20 minutes', 'moyen', '2026-04-10 07:50:00', FALSE),
(11, 'retard',   'Contrôle de police route de Thiès',  'faible', '2026-04-08 06:30:00', TRUE),
(15, 'accident', 'Accrochage léger à Pikine',           'moyen', '2026-03-25 09:20:00', FALSE),
(17, 'autre',    'Passager malaise, arrêt médical',     'grave', '2026-03-21 06:45:00', TRUE);
