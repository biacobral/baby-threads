# Baby Threads: Uso de Threads para simulação de um berçário virtual

Projeto desenvolvido para a disciplina de **Sistemas Operacionais**, com foco no estudo prático de concorrencia, disputas por recursos compartilhados e sincronização de threads em Python.

---

## Sobre o Projeto

Matéria: Sistemas Operacionais(C12)

Professor: Jonas

O objetivo do projeto é demonstrar o comportamento (e o **caos**) do uso de múltiplas **threads** disputando recursos em tempo real sem ou com sincronização.

A metáfora utilizada é a de um **Berçário Concorrente**:

* **Bebês (Threads):** Executam loops com intervalos aleatórios. Quando surge uma "vontade" (fome, fralda, sono), eles geram uma solicitação e a colocam na fila de atendimento compartilhada.
* **Cuidadoras (Threads):** Consumidoras que monitoram a fila compartilhada em tempo real para atender as demandas dos bebês.
* **Visualizador TUI (Thread):** Uma thread dedicada exclusivamente a renderizar o estado atual da fila, o status de cada bebê e as ações das cuidadoras diretamente via linha de comando (`terminal / cmd`).

---

## O Caos Programado (Conceitos de S.O. Explorados)

Este projeto expõe diversos problemas clássicos de concorrência:

1. **Condição de Corrida (*Race Conditions*):** Vários bebês tentando alterar a fila compartilhada simultaneamente.
2. **Seção Crítica:** Bloqueio e liberação de recursos compartilhados (como a fila e o status dos bebês).
3. **Starvation (Inanição):** Risco de um bebê chorar continuamente e não ser atendido caso a demanda supere a capacidade das cuidadoras.
4. **Produtor-Consumidor:** A relação direta entre os bebês (produtores de chamados) e as cuidadoras (consumidoras de chamados).

---

## Pré-requisitos e Como Executar

Não é necessária a instalação de bibliotecas externas (utiliza apenas os módulos nativos `threading`, `time`, `random`, `sys` e `os`).

### Executando o projeto:

```bash
python baby-threads.py <NUM_BEBES> <NUM_CUIDADORAS> <TEMPO_SIMULACAO>
```

**Exemplo:**

```bash
python baby-threads.py 5 2 15
```

*(Inicia 5 bebês, 2 cuidadoras rodando por 15 segundos).*

---

## Integrantes do Grupo

* **Beatriz Vaz Pedroso dos Santos Cobral** - GEC 2082
* **Felipe Silva Loschi** - GES 601
* **João Gabriel Chereze Rezende** - GEC 2040
* **Matheus Maciel Menezes Nascimento** - GEC 1971

---