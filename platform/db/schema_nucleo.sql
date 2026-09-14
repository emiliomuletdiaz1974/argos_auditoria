-- ═══════════════════════════════════════════════════════════════════════════
-- ARGOS · Esquema Núcleo de Base de Datos (PostgreSQL 16)
-- Componente ARG-005 · Cimientos de Plataforma
-- ═══════════════════════════════════════════════════════════════════════════

-- Extensiones requeridas
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── 1. Tabla de Diario Inmutable (Append-Only) ───────────────────────────
CREATE TABLE IF NOT EXISTS diario_inmutable (
    seq BIGINT PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    componente VARCHAR(32) NOT NULL,
    operacion VARCHAR(64) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    payload_hash CHAR(64) NOT NULL,
    detalles JSONB NOT NULL DEFAULT '{}'::jsonb,
    hash_previo CHAR(64) NOT NULL,
    hash_actual CHAR(64) NOT NULL UNIQUE
);

-- Regla de Inmutabilidad Estricta: Prohibir UPDATE y DELETE en el diario
CREATE OR REPLACE FUNCTION fn_prohibir_modificacion_diario()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'VIOLACION DE INTEGRIDAD FORENSE: El diario inmutable de ARGOS no permite modificaciones ni borrados (seq=%)', OLD.seq;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_proteger_diario ON diario_inmutable;
CREATE TRIGGER trg_proteger_diario
    BEFORE UPDATE OR DELETE ON diario_inmutable
    FOR EACH ROW
    EXECUTE FUNCTION fn_prohibir_modificacion_diario();

-- Índices de consulta para correlación rápida y observabilidad
CREATE INDEX IF NOT EXISTS idx_diario_timestamp ON diario_inmutable (timestamp);
CREATE INDEX IF NOT EXISTS idx_diario_componente ON diario_inmutable (componente);
CREATE INDEX IF NOT EXISTS idx_diario_operacion ON diario_inmutable (operacion);

-- ── 2. Entidades de Inventario (Sistemas y Almacenes de Datos) ───────────
CREATE TABLE IF NOT EXISTS entidades_inventario (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre VARCHAR(128) NOT NULL,
    tipo VARCHAR(64) NOT NULL, -- 'database_sql', 'api_rest', 'filesystem', 'dicom', 'fhir'
    descripcion TEXT,
    configuracion JSONB NOT NULL DEFAULT '{}'::jsonb, -- Datos de conexión (solo lectura)
    es_activo BOOLEAN NOT NULL DEFAULT true,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- ── 3. Campañas de Auditoría ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS campanas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nombre VARCHAR(128) NOT NULL,
    norma VARCHAR(64) NOT NULL, -- 'RGPD', 'AI_ACT', 'ENS_ALTO', 'DORA', 'EHDS'
    estado VARCHAR(32) NOT NULL DEFAULT 'CREADA', -- 'CREADA', 'EN_EJECUCION', 'SELLADA', 'FALLIDA'
    iniciada_en TIMESTAMPTZ,
    finalizada_en TIMESTAMPTZ,
    merkle_root CHAR(64), -- Raíz del árbol de Merkle calculada al sellar (Fase 07)
    sello_tpm TEXT,       -- Firma criptográfica del expediente
    creado_en TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- ── 4. Hallazgos de Conformidad ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hallazgos (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campana_id UUID NOT NULL REFERENCES campanas(id) ON DELETE RESTRICT,
    articulo_norma VARCHAR(64) NOT NULL, -- Ej: 'RGPD-Art-17' (Derecho al olvido)
    severidad VARCHAR(16) NOT NULL,      -- 'CRITICA', 'ALTA', 'MEDIA', 'BAJA', 'INFO'
    descripcion TEXT NOT NULL,
    evidencia_hash CHAR(64) NOT NULL,
    estado_remediacion VARCHAR(32) NOT NULL DEFAULT 'ABIERTO', -- 'ABIERTO', 'EN_REMEDIACION', 'CERRADO_VERIFICADO'
    detectado_en TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
