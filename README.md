# twin — Personal Cognitive OS (v0.2)

Camada **local-first** de memória, julgamento, privacidade e contexto pessoal,
consultável por qualquer LLM/ferramenta via **MCP**, API HTTP local e CLI.

Não é um chatbot, nem um RAG genérico, nem um agente. É infraestrutura:
suas ferramentas (Cursor, Claude Desktop, Claude Code, …) consultam o `twin`
e passam a saber onde você está no projeto, o que já foi decidido e como você
pensa — sem que você reexplique. **Modelos locais (Ollama) para tudo por
padrão; PostgreSQL + pgvector como armazenamento primário.**

## Arquitetura em camadas

```
External World
      │
      ▼
┌─ Sensory Layer ────────────── twin/sensory ──┐
│  Sensors: document · meeting · slack          │  cada fonte é um "sentido";
│  (futuros: email, calendar, browser, audio)   │  novos sensores não tocam
│         → Normalized Percepts                 │  nada rio abaixo
└───────────────────────┬───────────────────────┘
                        ▼
┌─ Cognitive Core ───────────── twin/cognition ─┐
│  extraction (Ollama → Anthropic → heurística)  │
│  dedupe · observer (atenção) · context pack    │
└───────┬───────────────────────────┬────────────┘
        ▼                           ▼
┌─ Memory System ─ twin/memory ┐  ┌─ Judgment System ─ twin/judgment ┐
│  stores: Postgres+pgvector    │  │  PII filter · Domain Firewall    │
│  (primário) · SQLite (dev)    │  │  judgment profile (YAML)         │
│  embeddings · hybrid search   │  │  log auditável de bloqueios      │
└───────────────┬───────────────┘  └────────────────┬─────────────────┘
                ▼                                   ▼
┌─ Interfaces ─────────────── twin/interfaces ──────────────────────────┐
│  MCP (Cursor/Claude Desktop/Claude Code) · API HTTP + review UI · CLI │
└───────────────────────────────────────────────────────────────────────┘
```

**Percept** é o contrato entre sensores e cognição — toda fonte, seja qual
for, vira isto:

```json
{
  "percept_type": "meeting_transcript",
  "source_sensor": "meeting",
  "occurred_at": "2026-07-01",
  "actors": ["Edu", "Marina"],
  "content": "…texto normalizado…",
  "content_refs": [{"kind": "file", "path": "…"}],
  "attachments": [],
  "privacy_hints": {"domain_hint": "work"},
  "integrity": {"content_hash": "…", "size_bytes": 1234}
}
```

## Setup

```bash
# 1. Infra local: Postgres+pgvector e Ollama
docker compose up -d
docker compose exec ollama ollama pull qwen3:8b          # extração
docker compose exec ollama ollama pull nomic-embed-text  # embeddings

# 2. Instalação
pip install -e ".[dev]"           # ou granular: .[api,mcp,postgres,anthropic]

# 3. Config e init
export TWIN_DB_URL=postgresql://twin:twin@localhost:5432/twin
twin init
```

Sem Docker/Postgres? Sem Ollama? Tudo degrada de forma explícita: SQLite
como store (`TWIN_DB_URL` vazio), embedder hash local e extrator heurístico
por regras. Nada quebra — mas o caminho primário é Postgres + Ollama.

## Fluxo básico

```bash
twin ingest ./docs ./transcripts ./meetings   # sensores → percepts
twin extract                                  # percepts → memórias candidatas
twin review                                   # revisão seletiva (ou: twin serve → UI web)
twin search "qual stack usamos no serviço de webhooks"
twin pack "escrever RFC de arquitetura do Atlas" --domain technical
twin observe "estou revisando o retry dos webhooks"
twin reindex                                  # após trocar de embedder
twin export                                   # dump JSON completo, sem lock-in
```

## Modelos locais (Ollama)

| papel | default | config |
|---|---|---|
| extração de memórias | `qwen3:8b` via `/api/chat` + structured outputs | `TWIN_OLLAMA_MODEL` |
| embeddings | `nomic-embed-text` via `/api/embed` | `TWIN_OLLAMA_EMBED_MODEL` |
| servidor | `http://127.0.0.1:11434` | `TWIN_OLLAMA_URL` |

Seleção do extrator (`TWIN_EXTRACTOR`): `auto` (default) tenta **Ollama →
Anthropic (se houver credencial) → heurística**; ou force `ollama` /
`anthropic` / `heuristic`. Qualquer texto que fosse sair da máquina passa
antes pelo filtro de PII (e-mails, telefones, CPF/CNPJ, cartões, chaves,
senhas) — com Ollama nada sai de qualquer forma, e o mascaramento roda mesmo
assim como defesa em profundidade.

Embeddings (`TWIN_EMBEDDER`): `auto` usa Ollama se estiver de pé, senão o
hash local determinístico. Cada embedding é gravado com o nome do modelo e
buscas nunca misturam modelos diferentes; `twin reindex` regenera tudo após
uma troca.

## Armazenamento

`TWIN_DB_URL` decide o backend por trás da interface única `MemoryStore`:

- **`postgresql://…`** (primário): pgvector para busca vetorial server-side
  (operador `<=>`), full-text nativo (tsvector + GIN, config `simple` para
  pt-BR + en), JSONB para payloads. Se a extensão pgvector não existir no
  servidor, degrada para similaridade client-side sem quebrar.
- **`sqlite:///…`** (dev/testes/fallback): FTS5 + cosine client-side,
  zero configuração.

O grafo (entidades + relações tipadas com validade temporal), evidências
verbatim, fila de revisão e log do firewall são idênticos nos dois backends.
Export JSON completo em `twin export` — o dado canônico é aberto.

## Domain Firewall e julgamento

- `~/.twin/policies.yaml`: regras declarativas (primeira que casa vence) com
  gates duros antes (status, validade temporal, confiança mínima) e
  default-deny para domínios sensíveis cruzando contexto. Todo bloqueio é
  logado em `firewall_log`.
- `~/.twin/judgment.yaml`: princípios, critérios de decisão e estilo — entra
  no topo de todo context pack para que LLMs diferentes ajam com o mesmo
  julgamento, não só os mesmos fatos.

## MCP

```bash
twin mcp    # stdio
```

```json
{ "mcpServers": { "twin": { "command": "twin", "args": ["mcp"] } } }
```

Tools: `memory_safe_context_pack` (principal), `memory_search`, `memory_get`,
`memory_related`, `memory_project_context`, `memory_recent_decisions`,
`memory_user_preferences`, `memory_judgment_profile`, `memory_observe`.

## API local

`twin serve` → `http://127.0.0.1:8765` (UI mínima de revisão) e API JSON em
`/api/*`: `ingest`, `extract`, `percepts`, `memories`, `search`,
`context_pack`, `observer`, `judgment`, `export`. Docs em `/docs`.

## Configuração (resumo)

| variável | default | efeito |
|---|---|---|
| `TWIN_HOME` | `~/.twin` | diretório de config (policies/judgment) |
| `TWIN_DB_URL` | `sqlite:///~/.twin/twin.db` | `postgresql://…` seleciona o backend primário |
| `TWIN_OLLAMA_URL` | `http://127.0.0.1:11434` | servidor Ollama |
| `TWIN_OLLAMA_MODEL` | `qwen3:8b` | modelo de extração |
| `TWIN_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | modelo de embeddings |
| `TWIN_EXTRACTOR` | `auto` | `auto` \| `ollama` \| `anthropic` \| `heuristic` |
| `TWIN_EMBEDDER` | `auto` | `auto` \| `ollama` \| `hash` |

## Testes

```bash
python -m pytest                                   # SQLite + mocks de Ollama
TWIN_TEST_PG_URL=postgresql://twin:twin@localhost:5432/twin \
python -m pytest                                   # + backend Postgres real
```

42 testes: percept contract, sensores, PII, extração, firewall, busca
híbrida, context pack, observer, API HTTP, MCP, cliente Ollama (transport
fake) e o store Postgres/pgvector de ponta a ponta.

## Escopo (o que esta versão não faz — de propósito)

Sem WhatsApp, redes sociais, saúde/família/relacionamento como fontes, sem
voz contínua, sem automações que agem sozinhas, sem chat próprio. Sensores
futuros (email, calendar, browser, audio, screen) entram como novos módulos
em `twin/sensory/sensors/` sem tocar as demais camadas.
