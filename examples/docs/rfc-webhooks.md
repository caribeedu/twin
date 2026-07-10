---
author: Edu
date: 2026-06-20
---

# RFC: Arquitetura de webhooks do projeto Atlas

## Contexto

O projeto Atlas precisa notificar sistemas externos quando pedidos mudam de
estado. Hoje isso é feito por polling, o que gera carga desnecessária no
banco.

## Decisão

Decidimos usar um outbox pattern com uma tabela `webhook_outbox` no Postgres e
um worker dedicado que publica os eventos. Optamos por não usar Kafka neste
momento: o volume atual (~2k eventos/dia) não justifica a complexidade
operacional.

Alternativas rejeitadas:
- Kafka: overhead operacional alto para o volume atual.
- Trigger + pg_notify: frágil em caso de reconexão do consumer.

## Consequências

- O worker de webhooks fica responsável por retry com backoff exponencial.
- TODO: Edu precisa revisar o esquema da tabela outbox até o fim do mês.
- Restrição: não podemos entregar payloads com dados de cartão — compliance
  PCI proíbe.
