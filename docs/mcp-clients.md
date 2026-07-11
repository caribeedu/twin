# Integrando o `twin` com clientes MCP

O `twin` expõe a memória via MCP por stdio: o cliente sobe o processo
`twin mcp` e conversa com ele localmente. Nada sai da máquina.

Pré-requisito: `pip install -e ".[mcp]"` (ou `.[dev]`) num Python acessível
ao cliente, e `twin init` executado. Se usa Postgres/Ollama, garanta que o
`docker compose up -d` esteja rodando antes de abrir o cliente.

> Dica geral: variáveis de ambiente (`TWIN_DB_URL`, `TWIN_OLLAMA_URL`, …)
> devem ir no bloco `env` da configuração do cliente — GUIs como o Claude
> Desktop não herdam o ambiente do seu shell.

## Claude Code

```bash
claude mcp add twin -- twin mcp
# escopo de projeto (compartilhável via .mcp.json):
claude mcp add --scope project twin -- twin mcp
```

Ou direto no `.mcp.json` do projeto:

```json
{
  "mcpServers": {
    "twin": {
      "command": "twin",
      "args": ["mcp"],
      "env": { "TWIN_DB_URL": "postgresql://twin:twin@localhost:5432/twin" }
    }
  }
}
```

## Claude Desktop

Edite o arquivo de configuração:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "twin": {
      "command": "/caminho/absoluto/para/twin",
      "args": ["mcp"],
      "env": { "TWIN_DB_URL": "postgresql://twin:twin@localhost:5432/twin" }
    }
  }
}
```

Use o caminho absoluto do executável (`which twin`) — apps de desktop nem
sempre têm o seu `PATH`. Reinicie o app após editar.

## Cursor

`~/.cursor/mcp.json` (global) ou `.cursor/mcp.json` na raiz do projeto:

```json
{
  "mcpServers": {
    "twin": {
      "command": "twin",
      "args": ["mcp"],
      "env": { "TWIN_DB_URL": "postgresql://twin:twin@localhost:5432/twin" }
    }
  }
}
```

Ative o servidor em Settings → MCP.

## Outros clientes stdio

Qualquer cliente compatível com MCP stdio funciona com:

```json
{ "command": "twin", "args": ["mcp"] }
```

## Como um cliente deve usar as tools

1. **Comece tarefas técnicas com `memory_safe_context_pack`**, passando uma
   descrição da tarefa em `query` e o `target_domain` correto (`technical`,
   `work`, `personal_preferences`, `assistant_preferences`). O pack vem em
   seções (judgment, decisions, constraints, tasks, preferences, facts,
   evidence) já filtradas pelo Domain Firewall.
2. Por padrão o pack só contém memórias **confirmadas** por humano. Só peça
   `include_candidates=true` quando estiver explorando, e nunca trate um
   `[candidate]` como fato estabelecido.
3. **Respeite `blocked`**: são memórias retidas pelo firewall de privacidade.
   Não tente contornar pedindo o conteúdo por outro caminho.
4. Use `memory_search`/`memory_get` para aprofundar, `memory_related` e
   `memory_project_context` para navegar o grafo, `memory_recent_decisions`
   antes de propor mudanças de arquitetura.
5. Cite `memory_id` quando usar conteúdo específico — todas as memórias têm
   evidência verbatim rastreável.
6. `memory_observe` serve para sugerir contexto durante uma conversa em
   andamento; ele nunca responde ao usuário, apenas lembra.

## Troubleshooting

| sintoma | causa provável |
|---|---|
| servidor não aparece no cliente | caminho não absoluto / `twin` fora do PATH do app |
| `Unsupported TWIN_DB_URL` | `env` ausente na config do cliente |
| packs vazios | nada confirmado ainda — rode `twin review` ou passe `include_candidates=true` |
| busca semântica fraca | Ollama fora do ar (caiu para hash embedder) — suba o Ollama e rode `twin reindex` |
| erro de conexão Postgres | `docker compose up -d` não está rodando |
