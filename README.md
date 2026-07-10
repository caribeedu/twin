# twin — Personal Cognitive OS

`twin` é uma camada **local-first** de memória, julgamento, privacidade e contexto pessoal, consultável por qualquer LLM/ferramenta via **MCP**, API HTTP local e CLI.

O projeto nasce de uma pergunta prática: **como reduzir a fricção de ter que reexplicar minha vida, meus projetos, minhas decisões, meu estilo e meu contexto toda vez que abro uma nova LLM?**

A resposta proposta não é “criar mais um chatbot”. Também não é simplesmente “fazer um RAG”. O objetivo é construir uma infraestrutura pessoal, portátil e evolutiva: uma representação computacional da memória, do contexto e do julgamento do usuário, capaz de ser consumida por ferramentas diferentes — Cursor, Claude Desktop, Claude Code, ChatGPT, modelos locais, agentes futuros, interfaces de voz e, eventualmente, sistemas físicos.

Em uma frase:

> Não construir uma IA que lembra de mim; construir uma infraestrutura cognitiva pessoal que qualquer IA possa consultar com segurança.

---

## 1. Visão

A visão de longo prazo do `twin` é funcionar como um **exocórtex pessoal**: uma extensão externa da cognição do usuário, capaz de manter continuidade entre ferramentas, sessões, modelos e contextos.

O sistema deve preservar:

- fatos importantes;
- decisões tomadas;
- alternativas rejeitadas;
- tarefas e compromissos;
- preferências técnicas;
- preferências de comunicação;
- padrões de julgamento;
- crenças e opiniões que mudam com o tempo;
- relações entre pessoas, projetos, sistemas e eventos;
- evidências de onde cada memória veio;
- limites rígidos entre domínios da vida;
- privacidade, PII e controle humano.

A ambição final é se aproximar de uma experiência de **integração homem-máquina**: não uma IA distante, mas uma camada que parece cognitivamente acoplada ao usuário. A inspiração estética e emocional vem de ficção científica, ciborgues, Matrix, Half-Life, Dexter, robótica e interfaces homem-máquina, mas a implementação deve ser sóbria, local-first, auditável e incremental.

---

## 2. O problema

LLMs modernas são extremamente úteis, mas normalmente operam com contexto incompleto. Mesmo com janelas longas e memória de produto, o usuário ainda precisa repetir:

- quem ele é;
- como prefere respostas;
- o que já foi decidido;
- o que está tentando construir;
- quais restrições existem;
- quais trade-offs já foram avaliados;
- quais ferramentas usa;
- quais decisões antigas ainda valem;
- quais domínios não devem se misturar.

Para um usuário avançado de IA, RAG, MCP, vetorização, PII, pipelines e agentes, o problema não é “como carregar arquivos no contexto”. O problema é mais profundo:

> Como criar uma representação persistente, segura, linkável, temporal e interoperável da minha mente/contexto, para que diferentes LLMs consigam operar com menos explicação e mais entendimento?

O ponto central é que **integração não significa apenas baixa latência**. Latência ajuda, mas o que realmente falta é **compreensão operacional**: a IA precisa entender o que determinada memória significa, quando ela vale, em qual domínio ela pode ser usada e como ela deve afetar uma decisão.

---

## 3. O que o projeto não é

`twin` não deve ser entendido como:

- um chatbot;
- um app de notas;
- um RAG genérico;
- um agente autônomo;
- um banco vetorial com markdowns;
- um clone de Jarvis;
- uma UI própria para substituir ChatGPT, Claude ou Cursor.

O projeto é uma camada de infraestrutura:

```text
fontes pessoais/profissionais
        ↓
ingestão + normalização
        ↓
filtro PII + classificação de domínio
        ↓
extração de memórias estruturadas
        ↓
grafo temporal + evidências + índices
        ↓
firewall de privacidade + julgamento
        ↓
context packs seguros
        ↓
MCP / API / CLI / LLMs / IDEs / agentes
```

A UI principal continua podendo ser externa. O usuário não deve perder a conveniência de ferramentas existentes. Por isso o MCP é parte central da arquitetura.

---

## 4. Fundamentos acadêmicos e conceituais

O projeto é inspirado por várias áreas: filosofia da mente, ciência cognitiva, neurociência, psicologia, IA simbólica, knowledge graphs, interação humano-computador e arquiteturas cognitivas.

### 4.1 Extended Mind — Andy Clark e David Chalmers

A hipótese da **mente estendida**, proposta por Andy Clark e David Chalmers em “The Extended Mind” (1998), defende que ferramentas externas podem se tornar parte do processo cognitivo quando são confiáveis, disponíveis e integradas ao comportamento.

O exemplo clássico é Otto, uma pessoa com Alzheimer que usa um caderno como memória externa. Se uma pessoa neurotípica consulta a memória biológica e Otto consulta o caderno de modo igualmente confiável, Clark e Chalmers perguntam: funcionalmente, por que o caderno não faria parte do sistema cognitivo?

`twin` aplica essa intuição ao mundo de LLMs:

```text
usuário pensa / fala / escreve
        ↓
twin recupera contexto, julgamento e memórias relevantes
        ↓
LLM principal raciocina com esse substrato
        ↓
usuário continua pensando com a máquina
```

A meta não é apenas “armazenar dados”, mas criar um sistema acoplado à cognição do usuário.

### 4.2 4E Cognition

A corrente da **4E cognition** entende a cognição como:

- embodied — incorporada ao corpo;
- embedded — situada em ambiente;
- extended — estendida por ferramentas;
- enactive — produzida na interação ativa com o mundo.

Essa linha é relevante porque o projeto não trata pensamento como algo isolado dentro do cérebro. O usuário pensa com ferramentas, IDEs, documentos, reuniões, Slack, e-mail, calendário, voz, notas e LLMs. O `twin` tenta transformar esse conjunto disperso em uma camada computacional coerente.

### 4.3 Sistemas de memória

A psicologia cognitiva e a neurociência distinguem múltiplos sistemas de memória. Isso inspira a separação interna do projeto.

| Sistema cognitivo | Função | Abstração no `twin` |
|---|---|---|
| Memória episódica | eventos, reuniões, conversas, contexto temporal | `event`, `source`, `evidence`, timeline |
| Memória semântica | fatos, conceitos, relações consolidadas | `fact`, entidades, relações, grafo |
| Memória procedural | modos de fazer, hábitos, workflows | `procedure`, playbooks, scripts |
| Working memory | foco atual da tarefa | query atual, observer, context pack |
| Controle executivo | seleção, inibição, julgamento | Domain Firewall, policies, judgment profile |

O hipocampo inspira a camada de captura episódica e consolidação temporal. O córtex associativo inspira a memória semântica. O córtex pré-frontal inspira a camada de julgamento, inibição e seleção de contexto.

### 4.4 Hipocampo, consolidação e temporalidade

O hipocampo é associado à memória episódica, navegação contextual, ligação entre eventos e consolidação. Computacionalmente, isso sugere que o sistema não deve guardar apenas documentos brutos, mas eventos com:

- data;
- fonte;
- participantes;
- evidência;
- domínio;
- validade;
- relação com memórias anteriores.

Exemplo:

```text
2026-07-01
Reunião Atlas kickoff
Participantes: Edu, Marina, Rafael
Decisão: usar Postgres outbox + worker dedicado
Alternativa rejeitada: Kafka
Condição futura: revisitar Kafka se volume > 50k eventos/dia
```

Isso é mais útil que uma transcrição inteira jogada no contexto.

### 4.5 Córtex pré-frontal, julgamento e inibição

O córtex pré-frontal está associado a planejamento, controle executivo, inibição, seleção de ações, metas e tomada de decisão. A inspiração computacional é clara: memória sozinha não basta.

Sem julgamento, cada LLM interpreta o usuário de um jeito. Com julgamento explícito, diferentes modelos podem operar com princípios mais consistentes.

Exemplo:

```yaml
principles:
  - privacidade > conveniência em dados pessoais
  - manutenção > arquitetura bonita em projeto pessoal
  - não misturar contexto íntimo com trabalho
  - preferir clareza direta a polidez vazia
```

Isso é diferente de uma memória factual. É um modelo de decisão.

### 4.6 Amígdala, saliência e risco

A amígdala e circuitos límbicos estão associados a saliência emocional, medo, risco, recompensa e relevância afetiva. Em uma versão futura, o `twin` deve representar algo análogo a **saliência**:

- isso é urgente?
- isso é emocionalmente sensível?
- isso pode causar dano se vazar?
- isso é importante para decisões futuras?
- isso deve virar memória ou ser descartado?

No MVP, essa função aparece parcialmente como `sensitivity`, `confidence`, `needs_review` e `review_reason`.

### 4.7 Gânglios da base e seleção de ação

Gânglios da base são frequentemente associados a seleção de ação, hábitos e loops de decisão. Para o projeto, isso inspira versões futuras com automações seguras:

```text
memória + contexto + julgamento
        ↓
seleção de ação possível
        ↓
rascunho / lembrete / sugestão / automação com aprovação
```

O MVP não executa ações autônomas de propósito. Antes de agir, o sistema precisa aprender a lembrar, filtrar e julgar.

### 4.8 Global Workspace Theory — Bernard Baars, Stanislas Dehaene

A **Global Workspace Theory** propõe que vários módulos especializados operam em paralelo, mas apenas algumas informações se tornam globalmente disponíveis para atenção, linguagem, memória de trabalho e ação.

Isso inspira diretamente o **Memory Observer**:

```text
LLM principal conversa com o usuário
        ↓
um observador paralelo lê a tarefa/conversa
        ↓
busca memórias possivelmente relacionadas
        ↓
filtra por domínio, confiança e privacidade
        ↓
sugere contexto à IA principal
```

A experiência desejada é parecida com “lembrar” algo: o usuário não quer consultar manualmente uma base. O sistema deve sugerir aquilo que parece relevante, sem vazar conteúdo proibido.

### 4.9 ACT-R — John R. Anderson

ACT-R é uma arquitetura cognitiva que separa componentes declarativos e procedurais, com mecanismos de ativação, recuperação e produção. O projeto se inspira nessa separação:

- memória declarativa: fatos, eventos, decisões;
- memória procedural: como o usuário costuma fazer algo;
- produção/ação: regras e critérios de decisão;
- ativação: relevância da memória para o contexto atual.

`twin` não implementa ACT-R, mas adota a ideia de que memória e procedimento são categorias distintas.

### 4.10 Predictive Processing e Active Inference — Karl Friston

Modelos de predictive processing e active inference tratam o cérebro como um sistema que mantém modelos internos, prevê o mundo e atualiza crenças ao receber erro de previsão.

Para `twin`, isso implica que o sistema não deve guardar apenas frases soltas como “Edu prefere X”. Ele deve acompanhar a evolução de modelos mentais:

```text
2023: Edu achava microservices preferíveis para quase tudo.
2026: Edu passou a preferir modular monolith quando manutenção e simplicidade importam mais.
Motivo: experiência prática com complexidade operacional.
```

Isso pede temporalidade, contradição, supersedência e histórico de crenças.

### 4.11 Self-complexity e papéis sociais

A psicologia discute que uma pessoa não opera com um único “eu” homogêneo. Existem papéis sociais e contextuais:

- eu desenvolvedor;
- eu namorado;
- eu filho;
- eu amigo;
- eu gestor;
- eu paciente;
- eu investidor;
- eu indivíduo privado.

Esses papéis compartilham algumas memórias, mas não todas. Esse ponto é crucial para privacidade.

O `twin` não deve modelar apenas `Edu -> tudo`. Deve modelar:

```text
Edu
 ├── persona: developer
 │    └── domínio: work/technical
 ├── persona: partner
 │    └── domínio: relationship
 ├── persona: son
 │    └── domínio: family
 ├── persona: individual
 │    └── domínio: personal/health/finance
 └── persona: assistant-user
      └── domínio: assistant_preferences
```

### 4.12 IA simbólica: semantic networks, frames e scripts

Antes de LLMs, IA simbólica já representava conhecimento com semantic networks, frames e scripts.

`twin` reaproveita essas ideias:

- triples/edges: `Edu -> prefers -> pt-BR answers`;
- frames: decisão técnica com slots de contexto, alternativas, riscos e consequência;
- scripts: sequência recorrente de como o usuário decide ou trabalha;
- policies: regras explícitas de privacidade e julgamento.

Exemplo de frame:

```json
{
  "frame": "TechnicalDecision",
  "project": "Atlas",
  "decision": "Use Postgres outbox + dedicated worker",
  "alternatives_rejected": ["Kafka", "trigger + pg_notify"],
  "rationale": "Current volume does not justify operational complexity",
  "revisit_when": "volume > 50k events/day"
}
```

---

## 5. Conceito central: memória não basta

Um banco de memórias pode ajudar uma LLM a recuperar fatos. Mas isso não garante que ela aja como uma extensão do usuário.

O projeto precisa de três camadas:

```text
memória → julgamento → ação
```

### 5.1 Memória

Memória responde:

- o que aconteceu?
- o que foi decidido?
- quem participou?
- qual fonte prova isso?
- quando isso era verdadeiro?

### 5.2 Julgamento

Julgamento responde:

- como o usuário pensa?
- quais trade-offs ele valoriza?
- o que ele jamais quer misturar?
- que tom ele prefere?
- quando privacidade vence conveniência?
- quando simplicidade vence arquitetura elegante?

### 5.3 Ação

Ação responde:

- devo sugerir algo?
- devo gerar um rascunho?
- devo lembrar o usuário?
- devo ficar em silêncio?
- devo bloquear uma memória?
- devo pedir confirmação explícita?

O MVP foca principalmente em memória + firewall + julgamento inicial. Ação autônoma fica para versões futuras.

---

## 6. Separação de domínios

Um requisito central do projeto é impedir mistura indevida entre contextos.

Exemplos de falha grave:

- gerar documento de trabalho mencionando problema de relacionamento;
- usar contexto de saúde em uma tarefa técnica;
- misturar problemas profissionais com conversa familiar;
- expor dados de terceiros em LLM cloud;
- transformar uma memória candidata falsa em fato confirmado.

Por isso, cada memória possui:

```text
type
+ domain
+ persona
+ sensitivity
+ confidence
+ status
+ valid_from/valid_until
+ evidence
```

O Domain Firewall decide se uma memória pode entrar em determinado contexto.

Exemplo:

```yaml
rules:
  - name: relationship_not_allowed_outside_own_domain
    if:
      memory_domain: [relationship, family, health, emotional]
      target_domain: [work, technical, assistant_preferences, general]
    action: block
```

A regra não deve ser “recuperar tudo e confiar na LLM”. O correto é bloquear antes da LLM principal receber o conteúdo.

---

## 7. Arquitetura do MVP

O MVP atual prova uma coisa:

> É possível reduzir drasticamente a reexplicação de contexto em trabalho técnico, sem vazar domínios, usando memória estruturada, grafo temporal leve, vetores, FTS e MCP.

Arquitetura:

```text
fontes (docs, reuniões, Slack)
        │  ingestão + normalização
        ▼
filtro PII ──────────────► nada sensível sai para nuvem sem máscara
        │  extração (LLM Anthropic ou heurística local)
        ▼
memórias candidatas ──► dedupe ──► fila de revisão seletiva
        │  aprovação humana quando necessário
        ▼
SQLite: memórias + entidades + relações + evidências + embeddings + FTS5
        │
        ▼
busca híbrida ──► Domain Firewall ──► context pack compacto
        │                                    ▲
        ▼                                    │
MCP / API / CLI                    judgment profile (YAML)
```

---

## 8. Stack e decisões técnicas

### 8.1 Local-first

Tudo vive em `~/.twin` ou `$TWIN_HOME`:

- SQLite;
- policies YAML;
- judgment YAML;
- dados exportáveis;
- backups simples.

Backup = copiar a pasta.

Exportação completa = `twin export`.

### 8.2 SQLite como grafo leve

O MVP usa SQLite com tabelas de:

- sources;
- memories;
- evidence;
- entities;
- memory_entities;
- relations;
- embeddings;
- firewall_log;
- FTS5.

Essa escolha evita infraestrutura pesada cedo demais. Neo4j, FalkorDB ou Graphiti podem entrar depois, mas a memória canônica deve continuar exportável.

### 8.3 Vetores como índice, não como memória

Embeddings são úteis para busca semântica, mas não são a memória verdadeira.

Regra do projeto:

```text
grafo + eventos + evidências = memória canônica
vetores = índice regenerável
LLM = extrator/intérprete
MCP = interface
```

Isso evita lock-in e permite reindexar no futuro.

### 8.4 Busca híbrida

A busca combina:

- FTS5/BM25;
- embeddings;
- boost por entidades;
- filtro por firewall.

A busca deve responder não apenas “o que parece semanticamente parecido?”, mas “o que é relevante, permitido e confiável para este contexto?”.

### 8.5 MCP-first

O projeto não deve depender de uma UI própria. O MCP permite que ferramentas externas consultem o `twin`.

Tools expostas:

| tool | função |
|---|---|
| `memory_safe_context_pack` | principal: pack compacto filtrado por firewall |
| `memory_search` | busca híbrida com filtro de domínio |
| `memory_get` | memória por id com evidências |
| `memory_related` | vizinhança de entidade no grafo |
| `memory_project_context` | contexto sobre um projeto |
| `memory_recent_decisions` | decisões recentes |
| `memory_user_preferences` | preferências estáveis |
| `memory_judgment_profile` | perfil de julgamento |
| `memory_observe` | observador de memória para texto/tarefa atual |

---

## 9. Modelo de dados

### 9.1 Memory Item

Um item de memória deve conter:

```json
{
  "id": "mem_...",
  "type": "event | fact | decision | preference | belief | task | procedure | relationship | communication_act | constraint",
  "title": "...",
  "summary": "...",
  "domain": "work | technical | personal_preferences | assistant_preferences | relationship | family | health | finance | legal | emotional | general",
  "persona": "developer | individual | partner | son | friend | manager | assistant-user",
  "sensitivity": "public | internal | private | restricted",
  "confidence": 0.0,
  "status": "candidate | confirmed | rejected | deprecated | contradicted",
  "valid_from": "YYYY-MM-DD",
  "valid_until": null,
  "payload": {},
  "needs_review": true,
  "review_reason": "...",
  "source_ids": ["src_..."],
  "entities": ["Atlas", "FastAPI", "Postgres"]
}
```

### 9.2 Tipos de memória

| Tipo | Significado |
|---|---|
| `event` | algo que aconteceu |
| `fact` | fato relativamente objetivo |
| `decision` | decisão tomada, com motivo e consequência |
| `preference` | preferência estável ou semiestável |
| `belief` | crença/opinião que pode mudar |
| `task` | tarefa, compromisso ou promessa |
| `procedure` | modo de fazer algo |
| `relationship` | relação entre pessoas/contextos |
| `communication_act` | ato comunicativo: pedido, promessa, recusa, desculpa, decisão |
| `constraint` | regra, limite ou proibição |

### 9.3 Evidência obrigatória

Toda memória deve carregar evidência, preferencialmente trecho verbatim da fonte.

Sem evidência, a memória é suspeita.

Isso reduz alucinação de memória e permite revisão humana.

### 9.4 Temporalidade

Memórias devem ter validade temporal.

Exemplo:

```text
2025: trabalha na Ambev
2026: trabalha na Shippo
```

Ambos podem ser verdadeiros, mas não simultaneamente.

Futuro desejado:

- `supersedes`;
- `contradicts`;
- `deprecated_by`;
- `valid_until` automático;
- timeline de crenças.

---

## 10. Pipeline de ingestão e extração

Fluxo:

```text
source bruto
        ↓
normalização
        ↓
filtro PII
        ↓
extração LLM ou heurística
        ↓
normalização de schema
        ↓
dedupe
        ↓
classificação de revisão
        ↓
grafo + evidência + embedding
```

Fontes do MVP:

- markdown;
- transcrições `.txt`;
- reuniões `.json` estilo Fireflies/Meetily;
- exports Slack `.json`;
- documentos técnicos.

Fontes futuras:

- Gmail;
- Outlook;
- WhatsApp;
- calendário;
- redes sociais;
- notas pessoais;
- tela/voz local;
- wearables;
- robótica/domótica.

---

## 11. PII e privacidade

O projeto assume que vazamento de dados pessoais pode causar dano real.

Antes de qualquer LLM cloud, o texto deve passar por máscara de PII.

Classes iniciais:

- e-mails;
- telefones;
- CPF;
- CNPJ;
- cartões;
- API keys;
- tokens;
- senhas;
- private keys.

Antes de fontes pessoais reais, expandir para:

- nomes próprios sensíveis;
- nomes de familiares;
- nomes de parceiros;
- endereços;
- dados bancários;
- dados médicos;
- URLs privadas;
- identificadores internos de empresa;
- links de Jira/GitHub privados;
- nomes de clientes;
- dados de terceiros.

Regra: dados sensíveis devem ser bloqueados, mascarados, hashados ou mantidos localmente.

---

## 12. Revisão seletiva

O usuário não deve revisar tudo manualmente. Revisão deve ocorrer por exceção.

Vai para revisão quando:

- confiança < limiar;
- sensibilidade `private` ou `restricted`;
- domínio fora do MVP;
- tipo próximo de julgamento (`belief`, `procedure`);
- memória parece atualizar/contradizer outra;
- há duplicidade parcial;
- a memória tem alto impacto;
- a fonte tem baixa confiabilidade;
- a memória pode afetar comportamento futuro.

Estados:

```text
candidate → confirmed
candidate → rejected
confirmed → deprecated
confirmed → contradicted
confirmed → superseded (futuro)
```

---

## 13. Judgment profile

Memórias dizem **o que aconteceu**.

Judgment diz **como o usuário pensa**.

Exemplo:

```yaml
principles:
  - privacidade > conveniência em dados pessoais
  - manutenção > arquitetura bonita em projeto pessoal
  - não misturar contexto íntimo com trabalho
  - preferir clareza direta a polidez vazia

technical_preferences:
  - evitar overengineering
  - preferir stack simples para MVP
  - avaliar lock-in antes de adotar ferramenta
  - dados canônicos em formato aberto, exportável

decision_criteria:
  - comparar custo de manutenção antes de performance
  - avaliar reversibilidade da decisão
  - medir utilidade real antes de expandir escopo

communication_style:
  language: pt-BR by default
  tone: direto, técnico, sem dicas básicas
```

Próximo passo importante: permitir que o sistema proponha alterações no judgment profile a partir de memórias confirmadas, mas **nunca escreva automaticamente sem aprovação humana**.

---

## 14. Memory Observer

O Memory Observer é uma IA/módulo paralelo que acompanha o texto atual e sugere memórias relacionadas.

Ele não responde pelo usuário. Ele não deve agir. Ele apenas lembra.

Fluxo:

```text
texto atual / tarefa / draft
        ↓
inferência de domínio
        ↓
busca de memórias candidatas
        ↓
firewall
        ↓
ranking
        ↓
sugestão compacta para IA principal
```

Isso é inspirado na Global Workspace Theory: muitos módulos operam em paralelo, mas apenas algumas informações entram no workspace global.

Formato desejado:

```json
{
  "inferred_domain": "technical",
  "suggested_context": [
    {
      "memory_id": "mem_...",
      "summary": "...",
      "why_relevant": "semantic similarity + entity match",
      "confidence": 0.87,
      "allowed": true
    }
  ],
  "blocked_context": [
    {
      "memory_id": "mem_...",
      "reason": "relationship_not_allowed_outside_own_domain"
    }
  ]
}
```

---

## 15. Instalação

```bash
pip install -e ".[dev]"        # tudo (api + mcp + testes)
# ou granular:
pip install -e ".[api,mcp,llm]"

twin init                      # cria ~/.twin (db, policies.yaml, judgment.yaml)
```

---

## 16. Fluxo básico

```bash
# 1. Ingestão: markdown, transcrições .txt, reuniões .json, Slack exports .json
twin ingest ./docs ./transcripts ./meetings

# 2. Extração de memórias
twin extract

# 3. Revisão seletiva
twin review            # terminal
twin serve             # UI web em http://127.0.0.1:8765

# 4. Consulta
twin search "qual stack usamos no serviço de webhooks"
twin pack "escrever RFC de arquitetura do Atlas" --domain technical
twin observe "estou revisando o retry dos webhooks"
```

---

## 17. MCP

```bash
twin mcp
```

Configuração em clientes compatíveis:

```json
{
  "mcpServers": {
    "twin": {
      "command": "twin",
      "args": ["mcp"]
    }
  }
}
```

Uso recomendado para clientes:

1. no começo de tarefas técnicas, chamar `memory_safe_context_pack`;
2. usar `target_domain` correto;
3. respeitar `blocked`;
4. não pedir memórias sensíveis sem autorização explícita;
5. citar fontes/memórias quando usar conteúdo específico;
6. não tratar `candidate` como fato definitivo.

---

## 18. API local

`twin serve` sobe:

- UI mínima de revisão;
- API JSON;
- docs interativas.

Endpoints principais:

```text
/api/ingest
/api/extract
/api/memories
/api/search
/api/context_pack
/api/observer
/api/judgment
/api/export
```

---

## 19. Configuração

| variável | default | efeito |
|---|---|---|
| `TWIN_HOME` | `~/.twin` | diretório de dados |
| `TWIN_EXTRACTOR` | `auto` | `auto` / `llm` / `heuristic` |
| `TWIN_EXTRACTION_MODEL` | `claude-opus-4-8` | modelo de extração |
| `TWIN_EMBEDDER` | `hash` | `hash` / `sentence-transformers` |

O embedder default é local, determinístico e regenerável. Embeddings não são fonte da verdade.

---

## 20. Testes

```bash
python -m pytest
```

Cobertura esperada:

- PII;
- ingestão;
- extração;
- dedupe;
- firewall;
- busca;
- context pack;
- observer;
- API;
- MCP.

---

## 21. Escopo do MVP

Inclui:

- memória técnica/profissional;
- docs técnicos;
- reuniões;
- Slack técnico;
- decisões;
- tarefas;
- preferências;
- grafo leve;
- busca híbrida;
- MCP;
- revisão seletiva;
- julgamento inicial.

Não inclui, de propósito:

- WhatsApp pessoal;
- redes sociais;
- saúde/família/relacionamento como fontes;
- voz contínua;
- automações autônomas;
- robótica;
- chat próprio;
- execução de ações sem confirmação;
- imitação completa da personalidade do usuário.

---

## 22. Roadmap

### v0.1 — Local Technical Memory

Provar que o sistema reduz reexplicação em trabalho técnico.

Entregas:

- ingestão local;
- extração;
- revisão;
- busca;
- MCP;
- firewall básico;
- judgment profile.

### v0.2 — MCP-first workflow

Objetivo: integração real com Cursor, Claude Desktop, Claude Code e clientes MCP.

Melhorias:

- context packs melhores;
- documentação para clientes;
- exemplos de uso;
- melhor ergonomia de instalação.

### v0.3 — Review system forte

Objetivo: qualidade de memória.

Melhorias:

- revisão por lotes;
- diff de memórias semelhantes;
- merge/supersede/contradict;
- source trust;
- métricas de precisão.

### v0.4 — Judgment model

Objetivo: fazer LLMs diferentes agirem com julgamento mais consistente.

Melhorias:

- sugestões de alteração no judgment profile;
- extração de critérios de decisão;
- separação entre preferência, crença e princípio;
- versionamento de julgamento.

### v0.5 — Domain Firewall avançado

Objetivo: preparar expansão para domínios pessoais.

Melhorias:

- policies por persona;
- permissões explícitas;
- logs auditáveis;
- redaction contextual;
- default-deny mais agressivo;
- candidate memories bloqueadas por padrão.

### v0.6 — Connectors profissionais

Fontes:

- Slack;
- Gmail profissional;
- Calendar;
- GitHub;
- docs;
- Fireflies;
- Meetily.

Objetivo: capturar conhecimento operacional do trabalho.

### v0.7 — Personal domains

Expansão cuidadosa para:

- finanças;
- casa;
- objetivos pessoais;
- relacionamento;
- família;
- saúde.

Com PII forte, revisão obrigatória e firewall mais rígido.

### v0.8 — Parallel Memory Observer

Objetivo: experiência mais próxima de cérebro estendido.

Melhorias:

- observer em tempo real;
- sugestões contextuais;
- confidence de domínio;
- memória espontânea;
- bloqueio silencioso de memórias proibidas.

### v0.9 — Voice companion

Objetivo: reduzir fricção de entrada.

Possibilidades:

- notas por voz;
- reflexão diária;
- captura local;
- baixa latência;
- interface conversacional sem substituir ferramentas existentes.

### v1.0 — Personal Cognitive OS

Uma versão confiável da infraestrutura:

- memória;
- julgamento;
- firewall;
- MCP;
- observer;
- revisão;
- exportação;
- backup;
- documentação;
- uso real diário.

---

## 23. Major versions futuras

### v2 — Extended Brain

Adicionar:

- memória episódica robusta;
- memória semântica consolidada;
- memória procedural;
- rotinas;
- objetivos;
- planejamento;
- reflexão diária/semanal;
- active persona.

### v3 — Cognitive Automation

Adicionar:

- lembretes inteligentes;
- rascunhos automáticos;
- follow-ups;
- detecção de compromissos;
- sugestões de ação;
- execução apenas com aprovação.

### v4 — Multimodal Life Layer

Adicionar:

- voz;
- tela;
- imagens;
- documentos;
- reuniões;
- ambiente;
- wearable data.

### v5 — Embodied / Robot-ready Memory

Preparar para agentes físicos:

- robôs pessoais;
- home assistant;
- memória espacial;
- preferências domésticas;
- rotinas físicas;
- interface com sistemas embarcados.

---

## 24. Projetos relacionados

### Graphiti / Zep

Relevantes para grafos temporais, memória de agentes, invalidação de fatos antigos e busca combinando grafo, texto e vetores.

Possível evolução do backend de grafo.

### Mem0

Relevante para consolidação de memória e decisão de “isso merece virar memória?”. Inspira lifecycle, extração e recuperação multi-sessão.

### Letta / MemGPT

Relevante para agentes stateful, memória de trabalho vs longo prazo e arquiteturas onde o agente gerencia sua própria memória.

### Meetily

Relevante para captura local de reuniões, transcrição e privacidade. Pode alimentar a camada episódica.

### Fireflies

Fonte útil de transcrições já existentes. Boa para ingestão retrospectiva, desde que filtrada por PII e confidencialidade.

### Slack MCP / conectores Slack

Fonte de decisões, blockers, contexto de equipe e compromissos. Alto valor, alto risco de vazamento. Deve entrar com domínio e políticas rigorosas.

### Screenpipe

Inspiração para captura local contínua de tela/áudio/contexto. Não é prioridade do MVP, mas relevante para versão multimodal.

---

## 25. Métricas de sucesso

### MVP

O MVP é bem-sucedido se:

- extrai decisões reais de docs/reuniões;
- gera evidência para cada memória;
- recupera contexto útil via MCP;
- não vaza domínios sensíveis;
- reduz reexplicação em tarefas técnicas;
- permite revisão humana prática;
- mantém dados exportáveis.

### Métricas possíveis

- precisão de extração;
- taxa de duplicatas;
- taxa de memórias inúteis;
- taxa de bloqueio correto;
- tamanho médio de context pack;
- tempo de resposta;
- número de revisões manuais por semana;
- número de vezes que o usuário precisou reexplicar contexto;
- satisfação subjetiva: “parece que a IA entendeu onde estou?”.

---

## 26. Riscos

### 26.1 Privacidade

Risco máximo. O sistema pode conter informações íntimas e profissionais. Mitigações:

- local-first;
- PII masking;
- firewall;
- logs;
- revisão;
- default-deny em domínios sensíveis;
- export/delete;
- criptografia futura.

### 26.2 Alucinação de memória

LLMs podem extrair memórias falsas. Mitigações:

- evidência obrigatória;
- confidence;
- candidate status;
- revisão seletiva;
- bloqueio de candidate em contextos críticos;
- citações internas.

### 26.3 Mistura de domínios

Risco operacional mais perigoso. Mitigações:

- domain/persona/sensitivity obrigatórios;
- firewall antes da LLM;
- logs de bloqueio;
- target_domain explícito;
- políticas testadas.

### 26.4 Overengineering

Risco de tentar construir o cérebro inteiro antes do MVP. Mitigação:

- começar por trabalho técnico;
- evitar WhatsApp/vida íntima no início;
- não criar chat próprio;
- usar MCP;
- medir utilidade real.

### 26.5 Dependência de fornecedor

Mitigação:

- dados canônicos em formato aberto;
- embeddings regeneráveis;
- LLM substituível;
- SQLite/export JSON;
- MCP como interface.

---

## 27. Próximas melhorias imediatas recomendadas

1. Bloquear `candidate` por padrão nos context packs.
2. Separar o context pack em seções: judgment, decisions, constraints, tasks, preferences, evidence.
3. Adicionar `source_trust`, `source_scope` e `source_confidentiality`.
4. Criar fluxo de “promover memória para judgment”.
5. Melhorar inferência de domínio do observer.
6. Expandir PII antes de fontes pessoais reais.
7. Adicionar criptografia local opcional.
8. Adicionar métricas de qualidade de memória.
9. Adicionar suporte a supersedência/contradição explícita.
10. Melhorar documentação de integração MCP com clientes reais.

---

## 28. Filosofia prática do projeto

`twin` deve seguir estes princípios:

```text
local-first > cloud-first
memória estruturada > texto bruto
julgamento explícito > imitação implícita
grafo temporal > markdown infinito
vetores como índice > vetores como verdade
MCP > UI própria obrigatória
firewall antes da LLM > confiança na LLM
revisão seletiva > curadoria manual total
evidência obrigatória > memória sem fonte
exportabilidade > lock-in
```

---

## 29. Definição final

`twin` é uma camada pessoal, local-first, interoperável e temporal de memória, julgamento, privacidade e contexto.

Ele existe para permitir que diferentes LLMs e ferramentas operem sobre uma representação consistente do usuário, sem exigir que o usuário reexplique sua vida, seus projetos e seu modo de pensar a cada nova sessão.

A frase-guia:

> Não quero apenas usar uma IA. Quero me sentir integrado à máquina, como se parte da minha cognição pudesse existir fora do meu cérebro, com segurança, continuidade e controle.

O MVP começa pequeno: memória técnica confiável via MCP.

O destino é maior: um cérebro estendido pessoal, portátil, privado e evolutivo.
