-- ============================================================
--  TranspoBot — Base de données MySQL
--  Projet GLSi L3 — ESP/UCAD
--  Pr. Ahmath Bamba MBACKE
-- ============================================================
--  Ce script crée et initialise la base de données TranspoBot,
--  un système de gestion de transport urbain.
--  Il contient :
--    1. La création de la base de données
--    2. La définition des tables (schéma)
--    3. Des données de test (jeu d'essai)
-- ============================================================


-- ------------------------------------------------------------
--  CRÉATION DE LA BASE DE DONNÉES
--  utf8mb4 : encodage Unicode complet (supporte les accents,
--             emojis, caractères spéciaux)
--  unicode_ci : comparaisons insensibles à la casse
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS transpobot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE transpobot;


-- ============================================================
--  DÉFINITION DES TABLES
-- ============================================================

-- ------------------------------------------------------------
--  TABLE : vehicules
--  Stocke les informations sur chaque véhicule de la flotte.
--  Un véhicule peut être un bus, un minibus ou un taxi.
-- ------------------------------------------------------------
CREATE TABLE vehicules (
    id               INT AUTO_INCREMENT PRIMARY KEY,  -- Identifiant unique auto-généré
    immatriculation  VARCHAR(20)  NOT NULL UNIQUE,    -- Plaque d'immatriculation (ex: DK-1234-AB), unique
    type             ENUM('bus','minibus','taxi') NOT NULL, -- Type de véhicule
    capacite         INT          NOT NULL,            -- Nombre de places assises
    statut           ENUM('actif','maintenance','hors_service') DEFAULT 'actif', -- État opérationnel du véhicule
    kilometrage      INT          DEFAULT 0,           -- Kilométrage total parcouru
    date_acquisition DATE,                             -- Date d'achat ou de mise en service
    created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP -- Date d'insertion automatique
);

-- ------------------------------------------------------------
--  TABLE : chauffeurs
--  Contient les données personnelles et professionnelles
--  de chaque chauffeur. Un chauffeur peut être assigné
--  à un véhicule (clé étrangère vers vehicules).
-- ------------------------------------------------------------
CREATE TABLE chauffeurs (
    id               INT AUTO_INCREMENT PRIMARY KEY,  -- Identifiant unique auto-généré
    nom              VARCHAR(100) NOT NULL,            -- Nom de famille du chauffeur
    prenom           VARCHAR(100) NOT NULL,            -- Prénom du chauffeur
    telephone        VARCHAR(20),                      -- Numéro de téléphone (optionnel)
    numero_permis    VARCHAR(30)  UNIQUE NOT NULL,     -- Numéro de permis de conduire (unique)
    categorie_permis VARCHAR(5),                       -- Catégorie du permis (ex: B, D)
    disponibilite    BOOLEAN      DEFAULT TRUE,        -- TRUE si le chauffeur est disponible
    vehicule_id      INT,                              -- Référence au véhicule assigné (NULL si non assigné)
    date_embauche    DATE,                             -- Date d'entrée dans l'entreprise
    created_at       TIMESTAMP    DEFAULT CURRENT_TIMESTAMP, -- Date d'insertion automatique
    FOREIGN KEY (vehicule_id) REFERENCES vehicules(id) -- Liaison avec la table vehicules
);

-- ------------------------------------------------------------
--  TABLE : lignes
--  Représente les itinéraires fixes (lignes de transport)
--  entre une origine et une destination.
--  Chaque ligne a un code unique et des caractéristiques
--  géographiques (distance, durée estimée).
-- ------------------------------------------------------------
CREATE TABLE lignes (
    id             INT AUTO_INCREMENT PRIMARY KEY,  -- Identifiant unique auto-généré
    code           VARCHAR(10)   NOT NULL UNIQUE,   -- Code court de la ligne (ex: L1, L2)
    nom            VARCHAR(100),                    -- Nom descriptif (ex: Ligne Dakar-Thiès)
    origine        VARCHAR(100)  NOT NULL,          -- Point de départ de la ligne
    destination    VARCHAR(100)  NOT NULL,          -- Point d'arrivée de la ligne
    distance_km    DECIMAL(6,2),                    -- Distance en kilomètres (précision 2 décimales)
    duree_minutes  INT                              -- Durée estimée du trajet en minutes
);

-- ------------------------------------------------------------
--  TABLE : tarifs
--  Définit les prix appliqués par ligne selon le profil
--  du passager (normal, étudiant, senior).
--  Relation many-to-one avec la table lignes.
-- ------------------------------------------------------------
CREATE TABLE tarifs (
    id           INT AUTO_INCREMENT PRIMARY KEY,  -- Identifiant unique auto-généré
    ligne_id     INT  NOT NULL,                   -- Référence à la ligne concernée
    type_client  ENUM('normal','etudiant','senior') DEFAULT 'normal', -- Catégorie tarifaire
    prix         DECIMAL(10,2) NOT NULL,           -- Prix en FCFA (2 décimales)
    FOREIGN KEY (ligne_id) REFERENCES lignes(id)  -- Liaison avec la table lignes
);

-- ------------------------------------------------------------
--  TABLE : trajets
--  Enregistre chaque voyage effectué sur une ligne donnée,
--  avec le chauffeur et le véhicule assignés.
--  Contient les données opérationnelles : horaires, passagers,
--  recette collectée et statut du trajet.
-- ------------------------------------------------------------
CREATE TABLE trajets (
    id                  INT AUTO_INCREMENT PRIMARY KEY,  -- Identifiant unique auto-généré
    ligne_id            INT      NOT NULL,               -- Ligne empruntée (référence à lignes)
    chauffeur_id        INT      NOT NULL,               -- Chauffeur du trajet (référence à chauffeurs)
    vehicule_id         INT      NOT NULL,               -- Véhicule utilisé (référence à vehicules)
    date_heure_depart   DATETIME NOT NULL,               -- Date et heure de départ effective
    date_heure_arrivee  DATETIME,                        -- Date et heure d'arrivée (NULL si trajet non terminé)
    statut              ENUM('planifie','en_cours','termine','annule') DEFAULT 'planifie', -- État du trajet
    nb_passagers        INT      DEFAULT 0,              -- Nombre de passagers transportés
    recette             DECIMAL(10,2) DEFAULT 0,         -- Recette totale collectée en FCFA
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Date d'insertion automatique
    FOREIGN KEY (ligne_id)     REFERENCES lignes(id),    -- Liaison avec la table lignes
    FOREIGN KEY (chauffeur_id) REFERENCES chauffeurs(id),-- Liaison avec la table chauffeurs
    FOREIGN KEY (vehicule_id)  REFERENCES vehicules(id)  -- Liaison avec la table vehicules
);

-- ------------------------------------------------------------
--  TABLE : incidents
--  Recense les événements anormaux survenus durant un trajet
--  (pannes, accidents, retards, etc.).
--  Chaque incident est lié à un trajet précis et peut être
--  marqué comme résolu ou non.
-- ------------------------------------------------------------
CREATE TABLE incidents (
    id             INT AUTO_INCREMENT PRIMARY KEY,  -- Identifiant unique auto-généré
    trajet_id      INT      NOT NULL,               -- Trajet durant lequel l'incident s'est produit
    type           ENUM('panne','accident','retard','autre') NOT NULL, -- Nature de l'incident
    description    TEXT,                            -- Description détaillée de l'incident
    gravite        ENUM('faible','moyen','grave') DEFAULT 'faible', -- Niveau de gravité
    date_incident  DATETIME NOT NULL,               -- Date et heure de l'incident
    resolu         BOOLEAN  DEFAULT FALSE,          -- FALSE = incident ouvert, TRUE = résolu
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- Date d'insertion automatique
    FOREIGN KEY (trajet_id) REFERENCES trajets(id)  -- Liaison avec la table trajets
);


-- ============================================================
--  DONNÉES DE TEST (JEU D'ESSAI)
--  Ces données permettent de tester l'application sans
--  avoir à saisir manuellement des enregistrements.
-- ============================================================

-- ------------------------------------------------------------
--  Insertion des véhicules
--  5 véhicules : 2 bus, 2 minibus, 1 taxi
--  Statuts variés : actif, maintenance, hors_service
-- ------------------------------------------------------------
INSERT INTO vehicules (immatriculation, type, capacite, statut, kilometrage, date_acquisition) VALUES
('DK-1234-AB', 'bus',     60, 'actif',       45000,  '2021-03-15'), -- Bus grande capacité, opérationnel
('DK-5678-CD', 'minibus', 25, 'actif',       32000,  '2022-06-01'), -- Minibus, opérationnel
('DK-9012-EF', 'bus',     60, 'maintenance', 78000,  '2019-11-20'), -- Bus ancien, en révision
('DK-3456-GH', 'taxi',     5, 'actif',      120000,  '2020-01-10'), -- Taxi à fort kilométrage
('DK-7890-IJ', 'minibus', 25, 'actif',       15000,  '2023-09-05'); -- Minibus récent, faible kilométrage

-- ------------------------------------------------------------
--  Insertion des chauffeurs
--  5 chauffeurs avec différentes catégories de permis.
--  BA Aminata (id=5) n'est pas encore assignée à un véhicule.
-- ------------------------------------------------------------
INSERT INTO chauffeurs (nom, prenom, telephone, numero_permis, categorie_permis, vehicule_id, date_embauche) VALUES
('DIOP',   'Mamadou', '+221771234567', 'P-2019-001', 'D', 1,    '2019-04-01'), -- Permis D (bus), véhicule 1
('FALL',   'Ibrahima','+221772345678', 'P-2020-002', 'D', 2,    '2020-07-15'), -- Permis D (bus), véhicule 2
('NDIAYE', 'Fatou',   '+221773456789', 'P-2021-003', 'B', 4,    '2021-02-01'), -- Permis B (voiture), véhicule 4
('SECK',   'Ousmane', '+221774567890', 'P-2022-004', 'D', 5,    '2022-10-20'), -- Permis D (bus), véhicule 5
('BA',     'Aminata', '+221775678901', 'P-2023-005', 'D', NULL, '2023-01-10'); -- Non assignée à un véhicule

-- ------------------------------------------------------------
--  Insertion des lignes de transport
--  4 lignes couvrant Dakar et ses alentours
-- ------------------------------------------------------------
INSERT INTO lignes (code, nom, origine, destination, distance_km, duree_minutes) VALUES
('L1', 'Ligne Dakar-Thiès',    'Dakar',       'Thiès',  70.5, 90),  -- Ligne interurbaine longue
('L2', 'Ligne Dakar-Mbour',    'Dakar',       'Mbour',  82.0, 120), -- Ligne côtière, la plus longue
('L3', 'Ligne Centre-Banlieue','Plateau',     'Pikine', 15.0, 45),  -- Ligne urbaine courte
('L4', 'Ligne Aéroport',       'Centre-ville','AIBD',   45.0, 60);  -- Navette vers l'aéroport AIBD

-- ------------------------------------------------------------
--  Insertion des tarifs par ligne et type de client
--  Trois catégories : normal, étudiant (réduit), senior (réduit)
--  Note : la ligne L3 n'a pas de tarif senior défini
-- ------------------------------------------------------------
INSERT INTO tarifs (ligne_id, type_client, prix) VALUES
(1, 'normal',   2500), (1, 'etudiant', 1500), (1, 'senior', 1800), -- Tarifs L1 (Dakar-Thiès)
(2, 'normal',   3000), (2, 'etudiant', 1800),                       -- Tarifs L2 (Dakar-Mbour)
(3, 'normal',    500), (3, 'etudiant',  300),                        -- Tarifs L3 (Centre-Banlieue)
(4, 'normal',   5000), (4, 'etudiant', 3000);                        -- Tarifs L4 (Aéroport)

-- ------------------------------------------------------------
--  Insertion des trajets effectués
--  27 trajets au total couvrant mars et avril 2026 :
--    - 22 trajets terminés
--    - 3 trajets en cours
--    - 1 trajet annulé
--  Les trajets en cours n'ont pas de date d'arrivée (NULL).
-- ------------------------------------------------------------
INSERT INTO trajets (ligne_id, chauffeur_id, vehicule_id, date_heure_depart, date_heure_arrivee, statut, nb_passagers, recette) VALUES
-- === Mars 2026 ===
(1, 1, 1, '2026-03-01 06:00:00', '2026-03-01 07:30:00', 'termine',  55, 137500), -- L1, DIOP, bus DK-1234-AB
(1, 2, 2, '2026-03-01 08:00:00', '2026-03-01 09:30:00', 'termine',  20,  50000), -- L1, FALL, minibus DK-5678-CD
(2, 3, 4, '2026-03-02 07:00:00', '2026-03-02 09:00:00', 'termine',   4,  12000), -- L2, NDIAYE, taxi DK-3456-GH
(3, 4, 5, '2026-03-05 07:30:00', '2026-03-05 08:15:00', 'termine',  22,  11000), -- L3, SECK, minibus DK-7890-IJ
(1, 1, 1, '2026-03-10 06:00:00', '2026-03-10 07:30:00', 'termine',  58, 145000), -- L1, DIOP, 2e trajet
(4, 2, 2, '2026-03-12 09:00:00', '2026-03-12 10:00:00', 'termine',  18,  90000), -- L4 Aéroport, FALL
(1, 5, 1, '2026-03-20 06:00:00', NULL,                  'en_cours', 45, 112500), -- En cours, BA Aminata
-- === Avril 2026 ===
(1, 1, 1, '2026-04-11 06:00:00', '2026-04-11 07:30:00', 'termine',  52, 130000),
(2, 2, 2, '2026-04-11 08:00:00', '2026-04-11 10:00:00', 'termine',  22,  66000),
(3, 3, 4, '2026-04-10 07:30:00', '2026-04-10 08:15:00', 'termine',  18,   9000),
(4, 4, 5, '2026-04-10 09:00:00', '2026-04-10 10:00:00', 'termine',  38, 190000),
(1, 5, 1, '2026-04-09 06:00:00', '2026-04-09 07:30:00', 'termine',  60, 150000), -- Bus plein (60/60)
(1, 1, 1, '2026-04-08 06:00:00', '2026-04-08 07:30:00', 'termine',  48, 120000),
(2, 2, 2, '2026-04-08 08:00:00', '2026-04-08 10:00:00', 'termine',  20,  60000),
(3, 4, 5, '2026-04-07 07:30:00', '2026-04-07 08:15:00', 'termine',  25,  12500),
(1, 3, 1, '2026-04-07 06:00:00', '2026-04-07 07:30:00', 'termine',  55, 137500),
(4, 5, 2, '2026-04-06 09:00:00', '2026-04-06 10:00:00', 'termine',  42, 210000), -- Meilleure recette L4
(1, 1, 1, '2026-04-04 06:00:00', '2026-04-04 07:30:00', 'termine',  58, 145000),
(2, 2, 2, '2026-04-02 08:00:00', '2026-04-02 10:00:00', 'termine',  24,  72000),
(3, 3, 4, '2026-03-31 07:30:00', '2026-03-31 08:15:00', 'termine',  15,   7500),
(1, 4, 5, '2026-03-28 06:00:00', '2026-03-28 07:30:00', 'termine',  50, 125000),
(4, 1, 1, '2026-03-25 09:00:00', '2026-03-25 10:00:00', 'termine',  35, 175000),
(2, 5, 2, '2026-03-23 08:00:00', NULL,                  'annule',    0,      0), -- Trajet annulé, recette nulle
(1, 2, 1, '2026-03-21 06:00:00', '2026-03-21 07:30:00', 'termine',  61, 152500), -- Surcharge (61 > 60 places)
(3, 3, 4, '2026-03-18 07:30:00', '2026-03-18 08:15:00', 'termine',  20,  10000),
(1, 1, 1, '2026-04-12 06:00:00', NULL,                  'en_cours', 45,      0), -- En cours, recette non encore comptabilisée
(2, 4, 5, '2026-04-12 08:00:00', NULL,                  'en_cours', 18,      0); -- En cours, recette non encore comptabilisée

-- ------------------------------------------------------------
--  Insertion des incidents
--  8 incidents recensés sur différents trajets :
--    - 4 résolus (resolu = TRUE)
--    - 4 ouverts  (resolu = FALSE)  ← affichés dans le badge nav
--  Types : retard (3), panne (2), accident (2), autre (1)
-- ------------------------------------------------------------
INSERT INTO incidents (trajet_id, type, description, gravite, date_incident, resolu) VALUES
(2,  'retard',   'Embouteillage au centre-ville',        'faible', '2026-03-01 08:45:00', TRUE),  -- Résolu
(3,  'panne',    'Crevaison pneu avant droit',           'moyen',  '2026-03-02 07:30:00', TRUE),  -- Résolu
(6,  'accident', 'Accrochage léger au rond-point',       'grave',  '2026-03-12 09:20:00', FALSE), -- ⚠ Ouvert
(8,  'retard',   'Embouteillage Dakar-Plateau matin',   'faible', '2026-04-11 08:45:00', TRUE),  -- Résolu
(9,  'panne',    'Surchauffe moteur, arrêt 20 minutes', 'moyen',  '2026-04-10 07:50:00', FALSE), -- ⚠ Ouvert
(11, 'retard',   'Contrôle de police route de Thiès',   'faible', '2026-04-08 06:30:00', TRUE),  -- Résolu
(15, 'accident', 'Accrochage léger à Pikine',            'moyen',  '2026-03-25 09:20:00', FALSE), -- ⚠ Ouvert
(17, 'autre',    'Passager malaise, arrêt médical',      'grave',  '2026-03-21 06:45:00', TRUE);  -- Résolu
-- Bilan : 3 incidents ouverts (ids 6, 9, 15) → badge nav affichera 3
