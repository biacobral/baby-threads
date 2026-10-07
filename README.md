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

## O Caos vs. A Ordem (Conceitos de S.O. Explorados)

Inicialmente, o projeto foi desenvolvido sem sincronização para evidenciar os problemas clássicos de concorrência:

1. **Condição de Corrida (*Race Conditions*):** Múltiplas threads disputando e alterando estruturas compartilhadas sem controle de acesso.
2. **Seção Crítica:** Acesso desordenado a recursos compartilhados como a fila de chamados e dicionários de status.
3. **Leituras Inconsistentes / Sujas:** Threads visualizadoras lendo estados intermediários em plena alteração.
4. **Atualizações Perdidas (*Lost Updates*):** Contadores globais incrementados concorrentemente sem atomicidade.
5. **Espera Ocupada (*Busy-Waiting*):** Threads aguardando eventos através de loops com polling.

---

## Dispositivos de Sincronização Implementados

Nesta etapa, foram implementados dispositivos canônicos de sincronização da biblioteca `threading`:

* **Mutex / Locks (`threading.Lock` e `threading.RLock`):**
  * `lock_metricas`: garante atomicidade e previne *lost updates* nos contadores globais de requisições, atendimentos e starvations.
  * `lock_atendimentos`: assegura integridade da lista compartilhada de histórico de atendimentos.
  * `lock_status`: protege os dicionários de status de bebês e cuidadoras contra leituras sujas e exceções de iteração concorrente na TUI e GUI.
  * `locks_bebes`: exclusão mútua estrita por bebê, garantindo que um bebê só possa ser manipulado por uma única cuidadora por vez.

* **Semáforos Contadores (`threading.Semaphore`):**
  * `semaforo_estacoes`: gerencia a alocação de recursos físicos finitos do berçário (postos/estações de atendimento simultâneo), exemplificando o controle de capacidade de Dijkstra.

* **Variáveis de Condição / Monitores (`threading.Condition`):**
  * Utilizado na fila de chamados compartilhada (`Fila` em `escalonamento.py`), coordenando produtores (`put()`) e consumidores (`get()`) com espera bloqueante (`wait_for`) e notificação (`notify()` / `notify_all()`), eliminando o *Check-Then-Act*.

* **Eventos de Sincronização (`threading.Event`):**
  * `eventos_atendido`: cada bebê possui um evento para sincronização direta com a cuidadora que o atende. A cuidadora sinaliza (`set()`) a conclusão do cuidado, acordando a thread do bebê imediatamente e eliminando completamente a espera ocupada (*busy-waiting*).

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

### Executando com interface gráfica:

O arquivo `baby-threads-gui.py` abre a mesma simulação em uma janela (Tkinter, nativo do Python), com os mesmos parâmetros:

```bash
python baby-threads-gui.py 5 2 15
```

A interface **não altera a simulação**: ela importa o `baby-threads.py`, dispara as mesmas threads de bebês e cuidadoras e apenas substitui a thread de renderização em texto. A tela mostra:

* **Fila compartilhada:** fichas coloridas por tipo de necessidade, na ordem em que serão atendidas.
* **Bebês:** um cartão por thread, com cor por estado (dormindo, brincando, chorando, sendo atendido) e uma barra de espera que fica vermelha ao ultrapassar o limite de starvation.
* **Cuidadoras:** estado atual e qual bebê está sendo atendido.
* **Problemas de concorrência:** contadores de condições de corrida, leituras inconsistentes e starvations, que piscam a cada nova ocorrência.
* **Log de eventos:** linha do tempo dos atendimentos e dos conflitos detectados.

Ao final do tempo, o relatório completo é exibido em uma janela e também impresso no terminal.

---

## Integrantes do Grupo

* **Beatriz Vaz Pedroso dos Santos Cobral** - GEC 2082
* **Felipe Silva Loschi** - GES 601
* **João Gabriel Chereze Rezende** - GEC 2040
* **Matheus Maciel Menezes Nascimento** - GEC 1971

---