--
-- PostgreSQL database dump
--

\restrict OeIDbeg4J56nSxIpWNI1hNmC94NmN8ooCzrjxpkhcSGztO1uLF7vkNxhuJrKL5B

-- Dumped from database version 15.19 (Debian 15.19-0+deb12u1)
-- Dumped by pg_dump version 15.19 (Debian 15.19-0+deb12u1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(80) NOT NULL,
    key_hash character varying(64) NOT NULL,
    prefix character varying(16) NOT NULL,
    suffix character varying(4) NOT NULL,
    status character varying(20) DEFAULT 'enabled'::character varying NOT NULL,
    last_used_at timestamp with time zone,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_api_key_status CHECK (((status)::text = ANY ((ARRAY['enabled'::character varying, 'disabled'::character varying, 'deleted'::character varying])::text[])))
);


--
-- Name: api_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: api_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.api_keys_id_seq OWNED BY public.api_keys.id;


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id bigint NOT NULL,
    actor_id integer,
    action character varying(80) NOT NULL,
    resource_type character varying(80) NOT NULL,
    resource_id character varying(100),
    client_ip character varying(45),
    result character varying(20) NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: backups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backups (
    id character varying(36) NOT NULL,
    status character varying(20) NOT NULL,
    actor_id bigint,
    size_bytes bigint,
    sha256 character varying(64),
    error_code character varying(60),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    CONSTRAINT ck_backup_status CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying, 'ready'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: call_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.call_logs (
    id bigint NOT NULL,
    request_id character varying(80) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    operation character varying(20) NOT NULL,
    user_id integer,
    user_group_id integer,
    api_key_id integer,
    provider_id integer,
    username_snapshot character varying(80),
    group_name_snapshot character varying(80),
    key_name_snapshot character varying(80),
    protocol character varying(30),
    request_model character varying(100),
    logical_model character varying(100),
    upstream_model character varying(200),
    provider_name_snapshot character varying(80),
    error_code character varying(80),
    client_ip character varying(64) NOT NULL,
    stream boolean NOT NULL,
    status character varying(30) NOT NULL,
    http_status integer NOT NULL,
    error_message text,
    input_tokens bigint,
    output_tokens bigint,
    cached_tokens bigint,
    total_tokens bigint,
    gateway_latency_ms double precision NOT NULL,
    upstream_latency_ms double precision,
    ttft_ms double precision,
    tokens_per_second double precision,
    trace jsonb NOT NULL,
    request_body jsonb,
    response_body jsonb
);


--
-- Name: call_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.call_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: call_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.call_logs_id_seq OWNED BY public.call_logs.id;


--
-- Name: compliance_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.compliance_logs (
    id bigint NOT NULL,
    request_id character varying(80) NOT NULL,
    user_id integer,
    group_id integer,
    model character varying(100),
    action character varying(20) NOT NULL,
    matches jsonb NOT NULL,
    elapsed_ms double precision NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: compliance_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.compliance_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: compliance_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.compliance_logs_id_seq OWNED BY public.compliance_logs.id;


--
-- Name: compliance_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.compliance_policies (
    id integer NOT NULL,
    name character varying(80) NOT NULL,
    action character varying(20) NOT NULL,
    status character varying(20) DEFAULT 'disabled'::character varying NOT NULL,
    word_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    sample_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    group_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    models jsonb DEFAULT '[]'::jsonb NOT NULL,
    threshold double precision DEFAULT '0.85'::double precision NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_compliance_action CHECK (((action)::text = ANY ((ARRAY['audit'::character varying, 'block'::character varying])::text[]))),
    CONSTRAINT ck_compliance_status CHECK (((status)::text = ANY ((ARRAY['enabled'::character varying, 'disabled'::character varying])::text[]))),
    CONSTRAINT ck_compliance_threshold CHECK (((threshold >= (0)::double precision) AND (threshold <= (1)::double precision)))
);


--
-- Name: compliance_policies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.compliance_policies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: compliance_policies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.compliance_policies_id_seq OWNED BY public.compliance_policies.id;


--
-- Name: logical_models; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.logical_models (
    name character varying(100) NOT NULL,
    model_type character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_logical_model_type CHECK (((model_type)::text = ANY ((ARRAY['text'::character varying, 'reasoning'::character varying, 'multimodal'::character varying, 'embedding'::character varying, 'rerank'::character varying, 'image'::character varying])::text[])))
);


--
-- Name: model_group_models; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_group_models (
    model_group_id integer NOT NULL,
    logical_model character varying(100) NOT NULL,
    "position" integer NOT NULL,
    CONSTRAINT ck_model_group_position CHECK (("position" >= 0))
);


--
-- Name: model_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_groups (
    id integer NOT NULL,
    name character varying(80) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    status character varying(20) DEFAULT 'enabled'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_model_group_status CHECK (((status)::text = ANY ((ARRAY['enabled'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: model_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.model_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: model_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.model_groups_id_seq OWNED BY public.model_groups.id;


--
-- Name: provider_model_mappings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.provider_model_mappings (
    id integer NOT NULL,
    provider_id integer NOT NULL,
    logical_model character varying(100) NOT NULL,
    upstream_model character varying(200) NOT NULL,
    model_type character varying(20) NOT NULL,
    status character varying(20) DEFAULT 'enabled'::character varying NOT NULL,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_mapping_status CHECK (((status)::text = ANY ((ARRAY['enabled'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: provider_model_mappings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.provider_model_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: provider_model_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.provider_model_mappings_id_seq OWNED BY public.provider_model_mappings.id;


--
-- Name: providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.providers (
    id integer NOT NULL,
    name character varying(80) NOT NULL,
    provider_type character varying(40) NOT NULL,
    protocol character varying(20) NOT NULL,
    protocol_config jsonb,
    protocol_type character varying(20),
    account_type character varying(40) DEFAULT 'standard'::character varying NOT NULL,
    CONSTRAINT ck_provider_category CHECK (protocol_type IS NULL OR protocol_type IN ('text','image','vector')),
    default_test_model character varying(100),
    base_url character varying(2048) NOT NULL,
    api_key_encrypted text,
    proxy character varying(2048),
    priority integer DEFAULT 0 NOT NULL,
    max_concurrency integer DEFAULT 10 NOT NULL,
    status character varying(20) DEFAULT 'enabled'::character varying NOT NULL,
    health_status character varying(20) DEFAULT 'unknown'::character varying NOT NULL,
    failure_count integer DEFAULT 0 NOT NULL,
    cooldown_until timestamp with time zone,
    remark text DEFAULT ''::text NOT NULL,
    config_version integer DEFAULT 0 NOT NULL,
    last_test_at timestamp with time zone,
    last_http_status integer,
    last_latency_ms integer,
    last_error_code character varying(40),
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_provider_health CHECK (((health_status)::text = ANY ((ARRAY['unknown'::character varying, 'healthy'::character varying, 'unhealthy'::character varying])::text[]))),
    CONSTRAINT ck_provider_limits CHECK (((max_concurrency > 0) AND (failure_count >= 0))),
    CONSTRAINT ck_provider_protocol CHECK (((protocol)::text = ANY ((ARRAY['openai'::character varying, 'anthropic'::character varying, 'ollama'::character varying])::text[]))),
    CONSTRAINT ck_provider_status CHECK (((status)::text = ANY ((ARRAY['enabled'::character varying, 'disabled'::character varying, 'deleted'::character varying])::text[])))
);


--
-- Name: providers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.providers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: providers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.providers_id_seq OWNED BY public.providers.id;


--
-- Name: quota_buckets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quota_buckets (
    group_id integer NOT NULL,
    period character varying(12) NOT NULL,
    period_start character varying(10) NOT NULL,
    reported_tokens bigint DEFAULT '0'::bigint NOT NULL,
    unreported_budget bigint DEFAULT '0'::bigint NOT NULL,
    reserved_budget bigint DEFAULT '0'::bigint NOT NULL,
    CONSTRAINT ck_quota_bucket_nonnegative CHECK (((reported_tokens >= 0) AND (unreported_budget >= 0) AND (reserved_budget >= 0)))
);


--
-- Name: quota_reservations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.quota_reservations (
    id character varying(80) NOT NULL,
    group_id integer NOT NULL,
    period character varying(12) NOT NULL,
    period_start character varying(10) NOT NULL,
    budget bigint NOT NULL,
    reported_tokens bigint,
    state character varying(20) DEFAULT 'active'::character varying NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_quota_reservation_nonnegative CHECK (((budget >= 0) AND ((reported_tokens IS NULL) OR (reported_tokens >= 0))))
);


--
-- Name: refresh_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.refresh_sessions (
    id character varying(36) NOT NULL,
    user_id integer NOT NULL,
    token_hash character varying(64) NOT NULL,
    csrf_hash character varying(64) NOT NULL,
    auth_version integer NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: review_samples; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.review_samples (
    id bigint NOT NULL,
    text text NOT NULL,
    text_hash character varying(64) NOT NULL,
    risk character varying(20) DEFAULT 'medium'::character varying NOT NULL,
    revision integer DEFAULT 1 NOT NULL,
    vector_status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    vector_error character varying(80),
    job_started_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_audit_sample_revision CHECK ((revision > 0)),
    CONSTRAINT ck_audit_sample_status CHECK (((vector_status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying, 'ready'::character varying, 'failed'::character varying])::text[])))
);


--
-- Name: review_samples_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.review_samples_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: review_samples_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.review_samples_id_seq OWNED BY public.review_samples.id;


--
-- Name: review_vectors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.review_vectors (
    sample_id bigint NOT NULL,
    embedding public.vector NOT NULL,
    model_version character varying(100) NOT NULL,
    sample_revision integer NOT NULL,
    CONSTRAINT ck_audit_vector_valid CHECK (((public.vector_dims(embedding) = 384) AND (public.vector_norm(embedding) > (0)::double precision)))
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id integer NOT NULL,
    code character varying(30) NOT NULL,
    name character varying(80) NOT NULL
);


--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;


--
-- Name: route_configs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.route_configs (
    id integer NOT NULL,
    virtual_model character varying(100) NOT NULL,
    embedding_model character varying(100) NOT NULL,
    simple_model_group integer NOT NULL,
    complex_model_group integer NOT NULL,
    top_k integer DEFAULT 5 NOT NULL,
    similarity_threshold double precision DEFAULT '0.75'::double precision NOT NULL,
    confidence_gap double precision DEFAULT '0.1'::double precision NOT NULL,
    fallback character varying(20) DEFAULT 'error'::character varying NOT NULL,
    status character varying(20) DEFAULT 'disabled'::character varying NOT NULL,
    vector_generation integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_route_config_distinct_groups CHECK ((simple_model_group <> complex_model_group)),
    CONSTRAINT ck_route_config_embedding CHECK (((virtual_model)::text <> (embedding_model)::text)),
    CONSTRAINT ck_route_config_fallback CHECK (((fallback)::text = ANY ((ARRAY['error'::character varying, 'simple'::character varying, 'complex'::character varying])::text[]))),
    CONSTRAINT ck_route_config_gap CHECK (((confidence_gap >= (0)::double precision) AND (confidence_gap <= (1)::double precision))),
    CONSTRAINT ck_route_config_generation CHECK ((vector_generation > 0)),
    CONSTRAINT ck_route_config_status CHECK (((status)::text = ANY ((ARRAY['enabled'::character varying, 'disabled'::character varying])::text[]))),
    CONSTRAINT ck_route_config_threshold CHECK (((similarity_threshold >= (0)::double precision) AND (similarity_threshold <= (1)::double precision))),
    CONSTRAINT ck_route_config_top_k CHECK (((top_k >= 1) AND (top_k <= 50)))
);


--
-- Name: route_configs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.route_configs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: route_configs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.route_configs_id_seq OWNED BY public.route_configs.id;


--
-- Name: route_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.route_decisions (
    id bigint NOT NULL,
    request_id character varying(80) NOT NULL,
    config_id integer NOT NULL,
    virtual_model character varying(100) NOT NULL,
    embedding_request_id character varying(80),
    source character varying(20) DEFAULT 'legacy' NOT NULL,
    request_kind character varying(20) DEFAULT 'real' NOT NULL,
    normalized_text text,
    confidence double precision,
    selected_model character varying(100),
    top_k integer NOT NULL,
    similarity double precision,
    classification character varying(20),
    selected_model_group integer,
    selected_group_name character varying(80),
    status character varying(20) NOT NULL,
    reason character varying(80),
    evidence jsonb DEFAULT '[]'::jsonb NOT NULL,
    elapsed_ms double precision NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_route_decision_source CHECK (source IN ('legacy','vector','local_rule','fallback','error')),
    CONSTRAINT ck_route_decision_kind CHECK (request_kind IN ('real','preview')),
    CONSTRAINT ck_route_decision_text CHECK (normalized_text IS NULL OR length(normalized_text)<=16000),
    CONSTRAINT ck_route_decision_confidence CHECK (confidence IS NULL OR (confidence>=0 AND confidence<=2)),
    CONSTRAINT ck_route_decision_class CHECK (((classification IS NULL) OR ((classification)::text = ANY ((ARRAY['simple'::character varying, 'complex'::character varying])::text[])))),
    CONSTRAINT ck_route_decision_elapsed CHECK (((elapsed_ms >= (0)::double precision) AND (elapsed_ms < 'Infinity'::double precision))),
    CONSTRAINT ck_route_decision_similarity CHECK (((similarity IS NULL) OR ((similarity >= ('-1'::integer)::double precision) AND (similarity <= (1)::double precision)))),
    CONSTRAINT ck_route_decision_status CHECK (((status)::text = ANY ((ARRAY['classified'::character varying, 'fallback'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_route_decision_top_k CHECK (((top_k >= 1) AND (top_k <= 50)))
);


--
-- Name: route_decisions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.route_decisions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: route_decisions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.route_decisions_id_seq OWNED BY public.route_decisions.id;


--
-- Name: route_samples; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.route_samples (
    id bigint NOT NULL,
    config_id integer NOT NULL,
    prompt text NOT NULL,
    prompt_hash character varying(64) NOT NULL,
    classification character varying(20) NOT NULL,
    vector_status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    vector_error character varying(80),
    revision integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    requested_by integer,
    vector_request_id character varying(80),
    job_started_at timestamp with time zone,
    CONSTRAINT ck_route_sample_class CHECK (((classification)::text = ANY ((ARRAY['simple'::character varying, 'complex'::character varying])::text[]))),
    CONSTRAINT ck_route_sample_prompt CHECK (((length(prompt) >= 1) AND (length(prompt) <= 16000))),
    CONSTRAINT ck_route_sample_revision CHECK ((revision > 0)),
    CONSTRAINT ck_route_sample_status CHECK (((vector_status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying, 'ready'::character varying, 'failed'::character varying, 'stale'::character varying])::text[])))
);


--
-- Name: route_samples_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.route_samples_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: route_samples_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.route_samples_id_seq OWNED BY public.route_samples.id;


--
-- Name: route_vectors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.route_vectors (
    sample_id bigint NOT NULL,
    embedding public.vector NOT NULL,
    dimensions integer NOT NULL,
    embedding_model character varying(100) NOT NULL,
    vector_generation integer NOT NULL,
    sample_revision integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_route_vector_dimensions CHECK ((((dimensions >= 1) AND (dimensions <= 4096)) AND (public.vector_dims(embedding) = dimensions))),
    CONSTRAINT ck_route_vector_nonzero CHECK ((public.vector_norm(embedding) > (0)::double precision)),
    CONSTRAINT ck_route_vector_revision CHECK (((vector_generation > 0) AND (sample_revision > 0)))
);


--
-- Name: sensitive_words; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sensitive_words (
    id integer NOT NULL,
    pattern character varying(256) NOT NULL,
    kind character varying(20) NOT NULL,
    risk character varying(20) DEFAULT 'medium'::character varying NOT NULL,
    status character varying(20) DEFAULT 'enabled'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_audit_word_kind CHECK (((kind)::text = ANY ((ARRAY['text'::character varying, 'wildcard'::character varying, 'regex'::character varying])::text[]))),
    CONSTRAINT ck_audit_word_status CHECK (((status)::text = ANY ((ARRAY['enabled'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: sensitive_words_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sensitive_words_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sensitive_words_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sensitive_words_id_seq OWNED BY public.sensitive_words.id;


--
-- Name: system_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_settings (
    key character varying(100) NOT NULL,
    value jsonb NOT NULL,
    scope character varying(30) DEFAULT 'basic'::character varying NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: usage_daily; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_daily (
    bucket timestamp with time zone NOT NULL,
    user_id integer NOT NULL,
    user_group_id integer NOT NULL,
    api_key_id integer NOT NULL,
    provider_id integer NOT NULL,
    request_model character varying(100) NOT NULL,
    logical_model character varying(100) NOT NULL,
    protocol character varying(100) NOT NULL,
    requests bigint NOT NULL,
    success bigint NOT NULL,
    failure bigint NOT NULL,
    usage_unavailable bigint NOT NULL,
    input_tokens_sum numeric(38,0) NOT NULL,
    input_tokens_count bigint NOT NULL,
    output_tokens_sum numeric(38,0) NOT NULL,
    output_tokens_count bigint NOT NULL,
    cached_tokens_sum numeric(38,0) NOT NULL,
    cached_tokens_count bigint NOT NULL,
    total_tokens_sum numeric(38,0) NOT NULL,
    total_tokens_count bigint NOT NULL,
    ttft_sum double precision NOT NULL,
    ttft_count bigint NOT NULL,
    tps_sum double precision NOT NULL,
    tps_count bigint NOT NULL,
    operation character varying(100) DEFAULT 'chat'::character varying NOT NULL
);


--
-- Name: usage_hourly; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.usage_hourly (
    bucket timestamp with time zone NOT NULL,
    user_id integer NOT NULL,
    user_group_id integer NOT NULL,
    api_key_id integer NOT NULL,
    provider_id integer NOT NULL,
    request_model character varying(100) NOT NULL,
    logical_model character varying(100) NOT NULL,
    protocol character varying(100) NOT NULL,
    requests bigint NOT NULL,
    success bigint NOT NULL,
    failure bigint NOT NULL,
    usage_unavailable bigint NOT NULL,
    input_tokens_sum numeric(38,0) NOT NULL,
    input_tokens_count bigint NOT NULL,
    output_tokens_sum numeric(38,0) NOT NULL,
    output_tokens_count bigint NOT NULL,
    cached_tokens_sum numeric(38,0) NOT NULL,
    cached_tokens_count bigint NOT NULL,
    total_tokens_sum numeric(38,0) NOT NULL,
    total_tokens_count bigint NOT NULL,
    ttft_sum double precision NOT NULL,
    ttft_count bigint NOT NULL,
    tps_sum double precision NOT NULL,
    tps_count bigint NOT NULL,
    operation character varying(100) DEFAULT 'chat'::character varying NOT NULL
);


--
-- Name: user_group_model_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_group_model_groups (
    user_group_id integer NOT NULL,
    model_group_id integer NOT NULL
);


--
-- Name: user_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_groups (
    id integer NOT NULL,
    name character varying(80) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    status character varying(20) DEFAULT 'enabled'::character varying NOT NULL,
    quota_limit bigint DEFAULT '0'::bigint NOT NULL,
    quota_period character varying(20) DEFAULT 'monthly'::character varying NOT NULL,
    max_concurrency integer DEFAULT 10 NOT NULL,
    key_max_concurrency integer DEFAULT 5 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_group_concurrency CHECK (((max_concurrency > 0) AND (key_max_concurrency > 0))),
    CONSTRAINT ck_group_period CHECK (((quota_period)::text = ANY ((ARRAY['daily'::character varying, 'monthly'::character varying, 'permanent'::character varying])::text[]))),
    CONSTRAINT ck_group_quota CHECK ((quota_limit >= 0)),
    CONSTRAINT ck_group_status CHECK (((status)::text = ANY ((ARRAY['enabled'::character varying, 'disabled'::character varying])::text[])))
);


--
-- Name: user_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_groups_id_seq OWNED BY public.user_groups.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    username character varying(80) NOT NULL,
    password_hash character varying(255) NOT NULL,
    role character varying(30) NOT NULL,
    status character varying(20) NOT NULL,
    must_change_password boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    role_id integer NOT NULL,
    user_group_id integer,
    name character varying(100) DEFAULT ''::character varying NOT NULL,
    email character varying(254),
    phone character varying(30),
    last_login_at timestamp with time zone,
    auth_version integer DEFAULT 0 NOT NULL,
    deleted_at timestamp with time zone
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: api_keys id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys ALTER COLUMN id SET DEFAULT nextval('public.api_keys_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: call_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.call_logs ALTER COLUMN id SET DEFAULT nextval('public.call_logs_id_seq'::regclass);


--
-- Name: compliance_logs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compliance_logs ALTER COLUMN id SET DEFAULT nextval('public.compliance_logs_id_seq'::regclass);


--
-- Name: compliance_policies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compliance_policies ALTER COLUMN id SET DEFAULT nextval('public.compliance_policies_id_seq'::regclass);


--
-- Name: model_groups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_groups ALTER COLUMN id SET DEFAULT nextval('public.model_groups_id_seq'::regclass);


--
-- Name: provider_model_mappings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_model_mappings ALTER COLUMN id SET DEFAULT nextval('public.provider_model_mappings_id_seq'::regclass);


--
-- Name: providers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers ALTER COLUMN id SET DEFAULT nextval('public.providers_id_seq'::regclass);


--
-- Name: review_samples id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_samples ALTER COLUMN id SET DEFAULT nextval('public.review_samples_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);


--
-- Name: route_configs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_configs ALTER COLUMN id SET DEFAULT nextval('public.route_configs_id_seq'::regclass);


--
-- Name: route_decisions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_decisions ALTER COLUMN id SET DEFAULT nextval('public.route_decisions_id_seq'::regclass);


--
-- Name: route_samples id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_samples ALTER COLUMN id SET DEFAULT nextval('public.route_samples_id_seq'::regclass);


--
-- Name: sensitive_words id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensitive_words ALTER COLUMN id SET DEFAULT nextval('public.sensitive_words_id_seq'::regclass);


--
-- Name: user_groups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_groups ALTER COLUMN id SET DEFAULT nextval('public.user_groups_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: api_keys api_keys_key_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_key_hash_key UNIQUE (key_hash);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: backups backups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backups
    ADD CONSTRAINT backups_pkey PRIMARY KEY (id);


--
-- Name: call_logs call_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.call_logs
    ADD CONSTRAINT call_logs_pkey PRIMARY KEY (id);


--
-- Name: call_logs call_logs_request_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.call_logs
    ADD CONSTRAINT call_logs_request_id_key UNIQUE (request_id);


--
-- Name: compliance_logs compliance_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compliance_logs
    ADD CONSTRAINT compliance_logs_pkey PRIMARY KEY (id);


--
-- Name: compliance_logs compliance_logs_request_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compliance_logs
    ADD CONSTRAINT compliance_logs_request_id_key UNIQUE (request_id);


--
-- Name: compliance_policies compliance_policies_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compliance_policies
    ADD CONSTRAINT compliance_policies_name_key UNIQUE (name);


--
-- Name: compliance_policies compliance_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compliance_policies
    ADD CONSTRAINT compliance_policies_pkey PRIMARY KEY (id);


--
-- Name: logical_models logical_models_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.logical_models
    ADD CONSTRAINT logical_models_pkey PRIMARY KEY (name);


--
-- Name: model_group_models model_group_models_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_group_models
    ADD CONSTRAINT model_group_models_pkey PRIMARY KEY (model_group_id, logical_model);


--
-- Name: model_groups model_groups_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_groups
    ADD CONSTRAINT model_groups_name_key UNIQUE (name);


--
-- Name: model_groups model_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_groups
    ADD CONSTRAINT model_groups_pkey PRIMARY KEY (id);


--
-- Name: provider_model_mappings provider_model_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_model_mappings
    ADD CONSTRAINT provider_model_mappings_pkey PRIMARY KEY (id);


--
-- Name: providers providers_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers
    ADD CONSTRAINT providers_name_key UNIQUE (name);


--
-- Name: providers providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.providers
    ADD CONSTRAINT providers_pkey PRIMARY KEY (id);


--
-- Name: quota_buckets quota_buckets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quota_buckets
    ADD CONSTRAINT quota_buckets_pkey PRIMARY KEY (group_id, period, period_start);


--
-- Name: quota_reservations quota_reservations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quota_reservations
    ADD CONSTRAINT quota_reservations_pkey PRIMARY KEY (id);


--
-- Name: refresh_sessions refresh_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_sessions
    ADD CONSTRAINT refresh_sessions_pkey PRIMARY KEY (id);


--
-- Name: refresh_sessions refresh_sessions_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_sessions
    ADD CONSTRAINT refresh_sessions_token_hash_key UNIQUE (token_hash);


--
-- Name: review_samples review_samples_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_samples
    ADD CONSTRAINT review_samples_pkey PRIMARY KEY (id);


--
-- Name: review_vectors review_vectors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_vectors
    ADD CONSTRAINT review_vectors_pkey PRIMARY KEY (sample_id);


--
-- Name: roles roles_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_code_key UNIQUE (code);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: route_configs route_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_configs
    ADD CONSTRAINT route_configs_pkey PRIMARY KEY (id);


--
-- Name: route_configs route_configs_virtual_model_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_configs
    ADD CONSTRAINT route_configs_virtual_model_key UNIQUE (virtual_model);


--
-- Name: route_decisions route_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_decisions
    ADD CONSTRAINT route_decisions_pkey PRIMARY KEY (id);


--
-- Name: route_decisions route_decisions_request_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_decisions
    ADD CONSTRAINT route_decisions_request_id_key UNIQUE (request_id);


--
-- Name: route_samples route_samples_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_samples
    ADD CONSTRAINT route_samples_pkey PRIMARY KEY (id);


--
-- Name: route_vectors route_vectors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_vectors
    ADD CONSTRAINT route_vectors_pkey PRIMARY KEY (sample_id);


--
-- Name: sensitive_words sensitive_words_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensitive_words
    ADD CONSTRAINT sensitive_words_pkey PRIMARY KEY (id);


--
-- Name: system_settings system_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (key);


--
-- Name: review_samples uq_audit_sample_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_samples
    ADD CONSTRAINT uq_audit_sample_hash UNIQUE (text_hash);


--
-- Name: logical_models uq_logical_model_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.logical_models
    ADD CONSTRAINT uq_logical_model_type UNIQUE (name, model_type);


--
-- Name: model_group_models uq_model_group_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_group_models
    ADD CONSTRAINT uq_model_group_position UNIQUE (model_group_id, "position");


--
-- Name: roles uq_role_id_code; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT uq_role_id_code UNIQUE (id, code);


--
-- Name: route_samples uq_route_sample_prompt; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_samples
    ADD CONSTRAINT uq_route_sample_prompt UNIQUE (config_id, prompt_hash);


--
-- Name: usage_daily usage_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_daily
    ADD CONSTRAINT usage_daily_pkey PRIMARY KEY (bucket, user_id, user_group_id, api_key_id, provider_id, request_model, logical_model, protocol, operation);


--
-- Name: usage_hourly usage_hourly_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.usage_hourly
    ADD CONSTRAINT usage_hourly_pkey PRIMARY KEY (bucket, user_id, user_group_id, api_key_id, provider_id, request_model, logical_model, protocol, operation);


--
-- Name: user_group_model_groups user_group_model_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_group_model_groups
    ADD CONSTRAINT user_group_model_groups_pkey PRIMARY KEY (user_group_id, model_group_id);


--
-- Name: user_groups user_groups_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_groups
    ADD CONSTRAINT user_groups_name_key UNIQUE (name);


--
-- Name: user_groups user_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_groups
    ADD CONSTRAINT user_groups_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: backups_one_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX backups_one_active ON public.backups USING btree ((true)) WHERE ((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying])::text[]));


--
-- Name: ix_api_keys_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_user_id ON public.api_keys USING btree (user_id);


--
-- Name: ix_audit_logs_actor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_actor_id ON public.audit_logs USING btree (actor_id);


--
-- Name: ix_audit_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_audit_logs_created_at ON public.audit_logs USING btree (created_at);


--
-- Name: ix_call_logs_api_key_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_api_key_id ON public.call_logs USING btree (api_key_id);


--
-- Name: ix_call_logs_api_key_id_created_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_api_key_id_created_id ON public.call_logs USING btree (api_key_id, created_at, id);


--
-- Name: ix_call_logs_created_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_created_id ON public.call_logs USING btree (created_at, id);


--
-- Name: ix_call_logs_logical_model_created_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_logical_model_created_id ON public.call_logs USING btree (logical_model, created_at, id);


--
-- Name: ix_call_logs_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_provider_id ON public.call_logs USING btree (provider_id);


--
-- Name: ix_call_logs_provider_id_created_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_provider_id_created_id ON public.call_logs USING btree (provider_id, created_at, id);


--
-- Name: ix_call_logs_request_model_created_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_request_model_created_id ON public.call_logs USING btree (request_model, created_at, id);


--
-- Name: ix_call_logs_status_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_status_created ON public.call_logs USING btree (status, created_at);


--
-- Name: ix_call_logs_user_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_user_created ON public.call_logs USING btree (user_id, created_at);


--
-- Name: ix_call_logs_user_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_user_group_id ON public.call_logs USING btree (user_group_id);


--
-- Name: ix_call_logs_user_group_id_created_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_user_group_id_created_id ON public.call_logs USING btree (user_group_id, created_at, id);


--
-- Name: ix_call_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_call_logs_user_id ON public.call_logs USING btree (user_id);


--
-- Name: ix_compliance_log_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_compliance_log_created ON public.compliance_logs USING btree (created_at);


--
-- Name: ix_provider_model_mappings_logical_model; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_provider_model_mappings_logical_model ON public.provider_model_mappings USING btree (logical_model);


--
-- Name: ix_provider_model_mappings_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_provider_model_mappings_provider_id ON public.provider_model_mappings USING btree (provider_id);


--
-- Name: ix_quota_reservations_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quota_reservations_expires_at ON public.quota_reservations USING btree (expires_at);


--
-- Name: ix_quota_reservations_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_quota_reservations_group_id ON public.quota_reservations USING btree (group_id);


--
-- Name: ix_refresh_sessions_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_refresh_sessions_expires_at ON public.refresh_sessions USING btree (expires_at);


--
-- Name: ix_refresh_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_refresh_sessions_user_id ON public.refresh_sessions USING btree (user_id);


--
-- Name: ix_route_decisions_created_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_route_decisions_created_id ON public.route_decisions USING btree (created_at, id);


--
-- Name: ix_route_decisions_virtual_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_route_decisions_virtual_created ON public.route_decisions USING btree (virtual_model, created_at);


--
-- Name: ix_route_samples_config_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_route_samples_config_status ON public.route_samples USING btree (config_id, vector_status);


--
-- Name: ix_usage_daily_user_bucket; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_daily_user_bucket ON public.usage_daily USING btree (user_id, bucket);


--
-- Name: ix_usage_hourly_user_bucket; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_usage_hourly_user_bucket ON public.usage_hourly USING btree (user_id, bucket);


--
-- Name: ix_users_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_role_id ON public.users USING btree (role_id);


--
-- Name: ix_users_user_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_user_group_id ON public.users USING btree (user_group_id);


--
-- Name: uq_active_provider_logical; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_active_provider_logical ON public.provider_model_mappings USING btree (provider_id, logical_model) WHERE (deleted_at IS NULL);


--
-- Name: api_keys api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: audit_logs audit_logs_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: backups backups_actor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backups
    ADD CONSTRAINT backups_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: provider_model_mappings fk_mapping_logical_model; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_model_mappings
    ADD CONSTRAINT fk_mapping_logical_model FOREIGN KEY (logical_model, model_type) REFERENCES public.logical_models(name, model_type) ON DELETE RESTRICT;


--
-- Name: users fk_user_group; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_user_group FOREIGN KEY (user_group_id) REFERENCES public.user_groups(id) ON DELETE RESTRICT;


--
-- Name: users fk_user_role; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_user_role FOREIGN KEY (role_id, role) REFERENCES public.roles(id, code) ON DELETE RESTRICT;


--
-- Name: model_group_models model_group_models_logical_model_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_group_models
    ADD CONSTRAINT model_group_models_logical_model_fkey FOREIGN KEY (logical_model) REFERENCES public.logical_models(name) ON DELETE RESTRICT;


--
-- Name: model_group_models model_group_models_model_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_group_models
    ADD CONSTRAINT model_group_models_model_group_id_fkey FOREIGN KEY (model_group_id) REFERENCES public.model_groups(id) ON DELETE CASCADE;


--
-- Name: provider_model_mappings provider_model_mappings_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_model_mappings
    ADD CONSTRAINT provider_model_mappings_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.providers(id) ON DELETE RESTRICT;


--
-- Name: quota_buckets quota_buckets_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quota_buckets
    ADD CONSTRAINT quota_buckets_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.user_groups(id) ON DELETE CASCADE;


--
-- Name: quota_reservations quota_reservations_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.quota_reservations
    ADD CONSTRAINT quota_reservations_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.user_groups(id) ON DELETE CASCADE;


--
-- Name: refresh_sessions refresh_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_sessions
    ADD CONSTRAINT refresh_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: review_vectors review_vectors_sample_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.review_vectors
    ADD CONSTRAINT review_vectors_sample_id_fkey FOREIGN KEY (sample_id) REFERENCES public.review_samples(id) ON DELETE CASCADE;


--
-- Name: route_configs route_configs_complex_model_group_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_configs
    ADD CONSTRAINT route_configs_complex_model_group_fkey FOREIGN KEY (complex_model_group) REFERENCES public.model_groups(id) ON DELETE RESTRICT;


--
-- Name: route_configs route_configs_embedding_model_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_configs
    ADD CONSTRAINT route_configs_embedding_model_fkey FOREIGN KEY (embedding_model) REFERENCES public.logical_models(name) ON DELETE RESTRICT;


--
-- Name: route_configs route_configs_simple_model_group_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_configs
    ADD CONSTRAINT route_configs_simple_model_group_fkey FOREIGN KEY (simple_model_group) REFERENCES public.model_groups(id) ON DELETE RESTRICT;


--
-- Name: route_configs route_configs_virtual_model_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_configs
    ADD CONSTRAINT route_configs_virtual_model_fkey FOREIGN KEY (virtual_model) REFERENCES public.logical_models(name) ON DELETE RESTRICT;


--
-- Name: route_samples route_samples_config_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_samples
    ADD CONSTRAINT route_samples_config_id_fkey FOREIGN KEY (config_id) REFERENCES public.route_configs(id) ON DELETE CASCADE;


--
-- Name: route_samples route_samples_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_samples
    ADD CONSTRAINT route_samples_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: route_vectors route_vectors_sample_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.route_vectors
    ADD CONSTRAINT route_vectors_sample_id_fkey FOREIGN KEY (sample_id) REFERENCES public.route_samples(id) ON DELETE CASCADE;


--
-- Name: user_group_model_groups user_group_model_groups_model_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_group_model_groups
    ADD CONSTRAINT user_group_model_groups_model_group_id_fkey FOREIGN KEY (model_group_id) REFERENCES public.model_groups(id) ON DELETE RESTRICT;


--
-- Name: user_group_model_groups user_group_model_groups_user_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_group_model_groups
    ADD CONSTRAINT user_group_model_groups_user_group_id_fkey FOREIGN KEY (user_group_id) REFERENCES public.user_groups(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict OeIDbeg4J56nSxIpWNI1hNmC94NmN8ooCzrjxpkhcSGztO1uLF7vkNxhuJrKL5B

