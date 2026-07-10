# twin — Personal Cognitive OS (MVP v0.1)

Camada **local-first** de memória, julgamento, privacidade e contexto pessoal,
consultável por qualquer LLM/ferramenta via **MCP**, API HTTP local e CLI.

O MVP prova uma coisa: **reduzir drasticamente a reexplicação de contexto em
trabalho técnico, sem vazar domínios**, usando memória estruturada (grafo
temporal leve + vetores + FTS) e um Domain Firewall auditável.

Não é um chatbot, nem um RAG genérico, nem um agente. É infraestrutura:
suas ferramentas (Cursor, Claude Desktop, Claude Code, …) consultam o `twin`
e passam a saber onde você está no projeto, o que já foi decidido e como você
pensa — sem que você reexplique.

```
fontes (docs, reuniões, Slack)
        │  ingestão + normalização
        ▼
   filtro PII  ──────────────►  nada sensível sai para a nuvem sem máscara
        │  extração (LLM Anthropic ou heurística local)
        ▼
memórias candidatas ──► dedupe ──► fila de revisão seletiva
        │  aprovação humana (UI/CLI) quando necessário
        ▼
 SQLite: memórias + entidades + relações + evidências + embeddings + FTS5
        │
        ▼
 busca híbrida ──► Domain Firewall ──► context pack compacto
        │                                    ▲
        ▼                                    │
   MCP / API / CLI                 judgment profile (YAML)
```

## Instalação

```bash
pip install -e ".[dev]"        # tudo (api + mcp + testes)
# ou granular: pip install -e ".[api,mcp,llm]"
twin init                      # cria ~/.twin (db, policies.yaml, judgment.yaml)
```

Tudo vive em um único diretório (`~/.twin` ou `$TWIN_HOME`): um SQLite, um
YAML de políticas e um YAML de julgamento. Backup = copiar a pasta.
Exportação completa: `twin export` (JSON aberto, sem lock-in).

## Fluxo básico

```bash
# 1. Ingestão: markdown, transcrições .txt, reuniões .json (Fireflies/Meetily),
#    exports do Slack .json — arquivos ou diretórios inteiros
twin ingest ./docs ./transcripts ./meetings

# 2. Extração de memórias (decisões, tarefas, preferências, fatos, crenças...)
twin extract

# 3. Revisão seletiva — só o que precisa de olho humano entra na fila
twin review            # no terminal
twin serve             # ou UI web em http://127.0.0.1:8765

# 4. Consulta
twin search "qual stack usamos no serviço de webhooks"
twin pack "escrever RFC de arquitetura do Atlas" --domain technical
twin observe "estou revisando o retry dos webhooks"
```

### Extração: LLM ou heurística

- Com credencial Anthropic (`ANTHROPIC_API_KEY` ou perfil `ant auth login`),
  a extração usa `claude-opus-4-8` com structured outputs — **sempre sobre o
  texto já mascarado de PII** (e-mails, telefones, CPF/CNPJ, cartões, chaves
  de API, senhas ficam locais).
- Sem credencial (ou `TWIN_EXTRACTOR=heuristic`), um extrator local por
  regras (pt-BR + en) encontra decisões/tarefas/preferências/restrições com
  confiança baixa — tudo cai na fila de revisão.
- Falha de rede/API degrada automaticamente para a heurística.

### Revisão seletiva

Vai para a fila apenas o que a política manda: confiança < 0.75,
sensibilidade `private`/`restricted`, tipos próximos de julgamento
(`belief`, `procedure`), domínio fora do MVP, ou possível
atualização/contradição de memória existente (similaridade 0.80–0.92).
Duplicatas (≥ 0.92) não geram memória nova — viram evidência extra da
existente. Toda memória carrega **evidência verbatim** da fonte.

## Domain Firewall

`~/.twin/policies.yaml` — regras declarativas, primeira que casa vence, com
gates duros antes (status, validade temporal, confiança mínima) e
default-deny para domínios sensíveis cruzando contexto. Todo bloqueio é
logado (`firewall_log`). Exemplo de regra:

```yaml
rules:
  - name: relationship_not_allowed_outside_own_domain
    if:
      memory_domain: [relationship, family, health, emotional]
      target_domain: [work, technical, assistant_preferences, general]
    action: block
```

Domínios do MVP: `work`, `technical`, `personal_preferences`,
`assistant_preferences` (os futuros já são aceitos e ficam retidos para
revisão).

## Judgment profile

`~/.twin/judgment.yaml` — princípios, critérios de decisão, preferências
técnicas e estilo de comunicação. Editado por você, lido pelas ferramentas.
Entra (com orçamento limitado) no topo de todo context pack, para que LLMs
diferentes ajam com o **mesmo julgamento**, não só os mesmos fatos.

## MCP

```bash
twin mcp        # stdio
```

Configuração no cliente (Claude Desktop / Cursor / Claude Code):

```json
{ "mcpServers": { "twin": { "command": "twin", "args": ["mcp"] } } }
```

Tools expostas:

| tool | função |
|---|---|
| `memory_safe_context_pack` | **principal** — pack compacto filtrado pelo firewall (judgment + memórias + fontes + bloqueios) |
| `memory_search` | busca híbrida (FTS5 + vetores + grafo) com filtro de domínio |
| `memory_get` | memória por id com evidências |
| `memory_related` | vizinhança de uma entidade no grafo |
| `memory_project_context` | tudo sobre um projeto |
| `memory_recent_decisions` | decisões recentes (opcionalmente por projeto) |
| `memory_user_preferences` | preferências estáveis, ranqueadas por contexto |
| `memory_judgment_profile` | o perfil de julgamento |
| `memory_observe` | Memory Observer: sugere memórias para o texto atual |

## API local

`twin serve` → `http://127.0.0.1:8765` (UI mínima de revisão) e API JSON em
`/api/*`: `ingest`, `extract`, `memories`, `search`, `context_pack`,
`observer`, `judgment`, `export`. Docs interativas em `/docs`.

## Configuração

| variável | default | efeito |
|---|---|---|
| `TWIN_HOME` | `~/.twin` | diretório de dados |
| `TWIN_EXTRACTOR` | `auto` | `auto` \| `llm` \| `heuristic` |
| `TWIN_EXTRACTION_MODEL` | `claude-opus-4-8` | modelo de extração |
| `TWIN_EMBEDDER` | `hash` | `hash` (local, zero deps) \| `sentence-transformers` |

O embedder default é um hashed bag-of-words local (determinístico,
regenerável). Trocar por `sentence-transformers` é uma mudança de config +
reindex — embeddings nunca são o dado canônico.

## Modelo de dados

- **Memory Item**: `type` (event/fact/decision/preference/belief/task/
  procedure/relationship/communication_act/constraint), `domain`, `persona`,
  `sensitivity` (public→restricted), `confidence`, `status`
  (candidate→confirmed/rejected/deprecated/contradicted), `valid_from`/
  `valid_until` (temporalidade), payload por tipo, evidências obrigatórias.
- **Grafo**: entidades (pessoas, projetos, sistemas) + relações tipadas
  (`works_on`, `prefers`, `affects`, `produced`, `supersedes`, …) com
  validade temporal, em SQLite (decisão de MVP; Graphiti/Neo4j é caminho de
  evolução com os mesmos dados exportáveis).
- **Índices**: FTS5 (BM25) + embeddings em blob; busca híbrida pondera
  texto (0.55) + semântica (0.35) + entidades (0.10).

## Testes

```bash
python -m pytest    # 29 testes: pii, ingestão, extração, firewall, busca, pack, observer, API, MCP
```

## Escopo (o que este MVP não faz — de propósito)

Sem WhatsApp, redes sociais, saúde/família/relacionamento como fontes, sem
voz contínua, sem automações que agem sozinhas, sem chat próprio. O caminho
de versões (v0.2 MCP-first → v0.3 review system → v0.4 judgment → v0.5
firewall avançado → …) está no documento-base do projeto.
