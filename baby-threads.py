#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baby Threads: Uso de Threads para simulação de um berçário virtual
Disciplina: Sistemas Operacionais (C12) - Inatel

Implementação COM mecanismos de sincronização.
Utiliza primitivas clássicas de concorrência e sincronização de Sistemas Operacionais:
  1. Mutex / Locks (threading.Lock, threading.RLock):
     - lock_metricas: exclusão mútua nos contadores globais (evita Lost Updates);
     - lock_atendimentos: integridade da lista de histórico de atendimentos;
     - lock_status: proteção dos dicionários de estado de bebês e cuidadoras contra leituras sujas/inconsistentes;
     - locks_bebes: exclusão mútua individual por bebê (apenas uma cuidadora atende o bebê por vez).
  2. Semáforos (threading.Semaphore):
     - semaforo_estacoes: controle de acesso aos recursos físicos/postos de atendimento finitos do berçário.
  3. Variáveis de Condição / Monitores (threading.Condition):
     - Gerenciamento da fila de pedidos (Produtor-Consumidor), bloqueando e acordando consumidoras sem polling.
  4. Eventos (threading.Event):
     - eventos_atendido: sinalização direta de conclusão do atendimento da cuidadora para o bebê,
       eliminando completamente a espera ocupada (busy waiting).
"""

import os
import random
import sys
import threading
import time

from escalonamento import NECESSIDADES, POLITICAS, criar_fila

# ==============================================================================
# VALIDAÇÃO DOS ARGUMENTOS DE LINHA DE COMANDO
# ==============================================================================
def exibir_ajuda():
    print("\nUso incorreto dos parâmetros.")
    print("Siga o formato: python baby-threads.py <NUM_BEBES> <NUM_CUIDADORAS> <TEMPO_SIMULACAO> [POLITICA]")
    print("Politicas: fifo (padrão), sjf, priority")
    print("Exemplo: python baby-threads.py 5 2 15 priority\n")
    sys.exit(1)

if len(sys.argv) < 4:
    exibir_ajuda()

try:
    num_bebes = int(sys.argv[1])
    num_cuidadoras = int(sys.argv[2])
    tempo_simulacao = int(sys.argv[3])
    if num_bebes <= 0 or num_cuidadoras <= 0 or tempo_simulacao <= 0:
        raise ValueError()
except ValueError:
    print("\nErro: Todos os parâmetros devem ser números inteiros positivos maiores que zero.")
    exibir_ajuda()

politica = sys.argv[4].lower() if len(sys.argv) > 4 else "fifo"
if politica not in POLITICAS:
    print(f"\nErro: política '{politica}' desconhecida.")
    exibir_ajuda()

# ==============================================================================
# DISPOSITIVOS DE SINCRONIZAÇÃO E RECURSOS COMPARTILHADOS
# ==============================================================================
# 1. Variável de Condição / Monitor: Fila sincronizada de Produtor-Consumidor
fila = criar_fila(politica)

# 2. Mutex / Lock: Proteção do histórico compartilhado de atendimentos
atendimentos = []
lock_atendimentos = threading.Lock()

# Tipos de necessidades suportadas pelo berçário
TIPOS_NECESSIDADES = list(NECESSIDADES)

def criar_necessidades(bebe_id):
    """Gera um chamado com necessidade aleatória, prioridade e duração do atendimento."""
    tipo = random.choice(TIPOS_NECESSIDADES)
    info = NECESSIDADES[tipo]
    return {
        "bebe_id": bebe_id,
        "tipo": tipo,
        "prioridade": info["prioridade"],
        "duracao": random.uniform(*info["duracao"]),
        "timestamp": time.time(),
    }

# 3. Mutex / RLock: Proteção dos estados compartilhados de bebês e cuidadoras
status_bebes = {}
status_cuidadoras = {}
lock_status = threading.RLock()

# 4. Mutex / Lock individual por bebê: Garante exclusão mútua estrita no atendimento do bebê
locks_bebes = {i: threading.Lock() for i in range(num_bebes)}

# 5. Eventos: Sinalização direta entre Cuidadora e Bebê (elimina espera ocupada / busy waiting)
eventos_atendido = {i: threading.Event() for i in range(num_bebes)}

# 6. Semáforo contador: Controla o acesso às estações de atendimento/recursos do berçário
semaforo_estacoes = threading.Semaphore(num_cuidadoras)

# 7. Mutex / Lock: Proteção dos contadores de métricas globais contra Lost Updates
metricas = {
    "conflitos_fila_pop": 0,      # Conflitos de Check-then-act eliminados com Condition Variable
    "erros_concorrencia_tui": 0,  # Leituras inconsistentes eliminadas com lock_status
    "total_pedidos_gerados": 0,
    "total_pedidos_atendidos": 0,
    "total_starvations": 0,
}
lock_metricas = threading.Lock()

rodando = True
tempo_inicio = time.time()
LIMITE_STARVATION = 3.0  # Segundos de espera para caracterizar starvation

# Inicialização dos estados dos bebês
for i in range(num_bebes):
    status_bebes[i] = {
        "id": i,
        "estado": "DORMINDO",  # DORMINDO, BRINCANDO, CHORANDO, SENDO_ATENDIDO
        "necessidade": None,   # fome, fralda, sono, higiene
        "inicio_espera": None,
        "tempo_espera_atual": 0.0,
        "total_pedidos": 0,
        "total_atendidos": 0,
        "starvation_count": 0,
        "atendido_evento": False,
    }

# Inicialização dos estados das cuidadoras
for j in range(num_cuidadoras):
    status_cuidadoras[j] = {
        "id": j,
        "estado": "OCIOSA",  # OCIOSA, ATENDENDO
        "atendendo_bebe": None,
        "necessidade_atual": None,
        "total_atendidos": 0,
    }


# ==============================================================================
# FUNÇÕES AUXILIARES THREAD-SAFE PARA LEITURA DE ESTADO
# ==============================================================================
def get_snapshot_bebes():
    """Retorna uma cópia snapshot consistente do estado dos bebês."""
    with lock_status:
        return {i: dict(b) for i, b in status_bebes.items()}

def get_snapshot_cuidadoras():
    """Retorna uma cópia snapshot consistente do estado das cuidadoras."""
    with lock_status:
        return {j: dict(c) for j, c in status_cuidadoras.items()}

def get_snapshot_metricas():
    """Retorna uma cópia snapshot consistente dos contadores de métricas."""
    with lock_metricas:
        return dict(metricas)


# ==============================================================================
# THREAD DO BEBÊ (PRODUTOR DE DEMANDAS)
# ==============================================================================
def rotina_bebe(bebe_id):
    """
    Simula o ciclo de vida de um bebê com dispositivos de sincronização:
    1. Brinca ou dorme por um período aleatório;
    2. Sente uma necessidade (fome, fralda, sono, higiene) e começa a chorar;
    3. Insere a solicitação na fila sincronizada (Produtor);
    4. Aguarda a notificação da cuidadora via Event (sem busy-waiting!).
    """
    global rodando

    while rodando:
        # Estado de repouso / brincadeira protegido por lock
        estado_inicial = random.choice(["BRINCANDO", "DORMINDO"])
        with lock_status:
            status_bebes[bebe_id]["estado"] = estado_inicial
            status_bebes[bebe_id]["necessidade"] = None
            status_bebes[bebe_id]["atendido_evento"] = False
            status_bebes[bebe_id]["tempo_espera_atual"] = 0.0

        tempo_calmo = random.uniform(1.0, 3.0)
        inicio_calmo = time.time()
        while rodando and (time.time() - inicio_calmo < tempo_calmo):
            time.sleep(0.05)

        if not rodando:
            break

        # Surge uma necessidade através da fábrica de necessidades
        pedido = criar_necessidades(bebe_id)
        necessidade = pedido["tipo"]

        with lock_status:
            status_bebes[bebe_id]["estado"] = "CHORANDO"
            status_bebes[bebe_id]["necessidade"] = necessidade
            status_bebes[bebe_id]["inicio_espera"] = pedido["timestamp"]
            status_bebes[bebe_id]["total_pedidos"] += 1

        # Incremento atômico protegido por lock_metricas (evita Lost Updates)
        with lock_metricas:
            metricas["total_pedidos_gerados"] += 1

        # Reseta o evento antes de enfileirar
        eventos_atendido[bebe_id].clear()

        # Insere na fila sincronizada (monitor com Condition Variable)
        fila.put(pedido)

        # Espera ser atendido via sincronização por evento (sem busy-waiting)
        sofreu_starvation = False
        while rodando and not eventos_atendido[bebe_id].is_set():
            # Aguarda eficientemente o evento de atendimento ou timeout de amostragem
            sinalizado = eventos_atendido[bebe_id].wait(timeout=0.1)
            if sinalizado:
                break

            with lock_status:
                inicio_espera = status_bebes[bebe_id]["inicio_espera"]
                espera = (time.time() - inicio_espera) if inicio_espera else 0.0
                status_bebes[bebe_id]["tempo_espera_atual"] = espera

            # Se a espera passar do limite de paciência, caracteriza inanição (starvation)
            if espera >= LIMITE_STARVATION and not sofreu_starvation:
                sofreu_starvation = True
                with lock_status:
                    status_bebes[bebe_id]["starvation_count"] += 1
                with lock_metricas:
                    metricas["total_starvations"] += 1

        with lock_status:
            status_bebes[bebe_id]["tempo_espera_atual"] = 0.0


# ==============================================================================
# THREAD DA CUIDADORA (CONSUMIDOR DE DEMANDAS)
# ==============================================================================
def rotina_cuidadora(cuidadora_id):
    """
    Simula o trabalho de uma cuidadora com dispositivos de sincronização:
    1. Consome chamados da fila sincronizada (bloqueante via Condition Variable);
    2. Adquire recurso físico via Semáforo e lock de exclusão mútua do bebê;
    3. Atende a necessidade do bebê pelo tempo previsto;
    4. Registra histórico e métricas de forma atômica com Locks;
    5. Dispara Evento sinalizando à thread do bebê a conclusão do atendimento.
    """
    global rodando

    while rodando:
        with lock_status:
            status_cuidadoras[cuidadora_id]["estado"] = "OCIOSA"
            status_cuidadoras[cuidadora_id]["atendendo_bebe"] = None
            status_cuidadoras[cuidadora_id]["necessidade_atual"] = None

        pedido = fila.get(timeout=0.1)
        if pedido is None:
            continue

        bebe_id = pedido["bebe_id"]
        necessidade = pedido["tipo"]
        tempo_espera = time.time() - pedido["timestamp"]

        # Adquire semáforo de recurso compartilhado (estação de atendimento)
        # e lock exclusivo do bebê atendido (seção crítica de cuidado)
        with semaforo_estacoes:
            with locks_bebes[bebe_id]:
                with lock_status:
                    status_cuidadoras[cuidadora_id]["estado"] = "ATENDENDO"
                    status_cuidadoras[cuidadora_id]["atendendo_bebe"] = bebe_id
                    status_cuidadoras[cuidadora_id]["necessidade_atual"] = necessidade
                    status_bebes[bebe_id]["estado"] = "SENDO_ATENDIDO"

                time.sleep(pedido["duracao"])

                # Conclusão do atendimento e gravação protegida no histórico
                with lock_atendimentos:
                    atendimentos.append((bebe_id, necessidade, tempo_espera))

                with lock_metricas:
                    metricas["total_pedidos_atendidos"] += 1

                with lock_status:
                    status_cuidadoras[cuidadora_id]["total_atendidos"] += 1
                    status_bebes[bebe_id]["total_atendidos"] += 1
                    status_bebes[bebe_id]["atendido_evento"] = True

                # Dispara evento para acordar a thread do bebê imediatamente!
                eventos_atendido[bebe_id].set()


# ==============================================================================
# THREAD DO VISUALIZADOR TUI (TERMINAL USER INTERFACE)
# ==============================================================================
def rotina_tui():
    """
    Renderiza em tempo real um painel no terminal com o status da simulação.
    Lê estruturas compartilhadas sob locks para garantir consistência e evitar
    leituras concorrentes corrompidas ou exceções de iteração.
    """
    global rodando

    while rodando:
        try:
            tempo_decorrido = time.time() - tempo_inicio
            tempo_restante = max(0.0, tempo_simulacao - tempo_decorrido)

            # Cópia visual da fila no instante da leitura
            fila_snapshot = list(fila)
            fila_str = ", ".join([f"B{p['bebe_id']}({p['tipo']})" for p in fila_snapshot[:8]])
            if len(fila_snapshot) > 8:
                fila_str += f" ... (+{len(fila_snapshot) - 8})"
            if not fila_str:
                fila_str = "[Vazia]"

            # Obtenção de snapshots consistentes sob lock
            bebes_snap = get_snapshot_bebes()
            cuidadoras_snap = get_snapshot_cuidadoras()
            m_snap = get_snapshot_metricas()

            linhas = []
            linhas.append("\033[H\033[J")  # ANSI escape para limpar a tela e posicionar o cursor
            linhas.append("=" * 78)
            linhas.append("BABY THREADS - BERÇÁRIO VIRTUAL CONCORRENTE".center(78))
            linhas.append("[ MODO SINCRONIZADO - MUTEX / SEMÁFOROS / EVENTS / COND VAR ]".center(78))
            linhas.append("=" * 78)
            linhas.append(f"Tempo: {tempo_decorrido:4.1f}s / {tempo_simulacao:4.1f}s | "
                          f"Bebês: {num_bebes} | Cuidadoras: {num_cuidadoras} | Restante: {tempo_restante:4.1f}s")
            linhas.append(f"Fila ({len(fila_snapshot)} item/itens): {fila_str}")
            linhas.append("-" * 78)

            # Painel dos Bebês
            linhas.append("STATUS DOS BEBÊS:")
            linhas.append("ID   Estado           Necessidade   Espera       Starvations   Atendimentos")
            for i in range(num_bebes):
                b = bebes_snap[i]
                estado = b["estado"]
                nec = b["necessidade"] if b["necessidade"] else "-"
                espera = b["tempo_espera_atual"]
                starv = b["starvation_count"]
                atend = b["total_atendidos"]

                tag_espera = f"{espera:4.1f}s"
                if espera >= LIMITE_STARVATION:
                    tag_espera += " ALERTA!"

                linhas.append(f"#{b['id']:02d}  {estado:<15}  {nec:<12}  {tag_espera:<11}  {starv:<12}  {atend}")

            linhas.append("-" * 78)

            # Painel das Cuidadoras
            linhas.append("STATUS DAS CUIDADORAS:")
            linhas.append("ID   Estado           Atendendo        Necessidade    Total Atendidos")
            for j in range(num_cuidadoras):
                c = cuidadoras_snap[j]
                estado = c["estado"]
                bebe_alvo = f"Bebê #{c['atendendo_bebe']:02d}" if c["atendendo_bebe"] is not None else "-"
                nec = c["necessidade_atual"] if c["necessidade_atual"] else "-"
                atend = c["total_atendidos"]
                linhas.append(f"#{c['id']:02d}  {estado:<15}  {bebe_alvo:<15}  {nec:<13}  {atend}")

            linhas.append("-" * 78)

            # Estatísticas em Tempo Real
            linhas.append("ESTATÍSTICAS DE SINCRONIZAÇÃO EM TEMPO REAL:")
            linhas.append(f"Conflitos de Corrida na Fila (IndexError):     {m_snap['conflitos_fila_pop']}")
            linhas.append(f"Falhas por Concorrência na Leitura da TUI:      {m_snap['erros_concorrencia_tui']}")
            linhas.append(f"Ocorrências de Inanição (Starvation > {LIMITE_STARVATION}s): {m_snap['total_starvations']}")
            linhas.append(f"Pedidos Gerados: {m_snap['total_pedidos_gerados']} | Atendidos: {m_snap['total_pedidos_atendidos']} | Fila Residual: {len(fila_snapshot)}")
            linhas.append("=" * 78)

            sys.stdout.write("\n".join(linhas) + "\n")
            sys.stdout.flush()

        except (RuntimeError, IndexError, KeyError):
            with lock_metricas:
                metricas["erros_concorrencia_tui"] += 1
        except Exception:
            with lock_metricas:
                metricas["erros_concorrencia_tui"] += 1

        time.sleep(0.25)


# ==============================================================================
# RELATÓRIO FINAL
# ==============================================================================
def exibir_relatorio_final():
    print("\n" + "=" * 78)
    print("RELATÓRIO FINAL DA SIMULAÇÃO".center(78))
    print("[ MODO SINCRONIZADO - SEÇÃO CRÍTICA & THREAD SAFETY ]".center(78))
    print("=" * 78)
    print(f"Duração configurada: {tempo_simulacao}s")
    print(f"Total de Threads Criadas: {num_bebes} bebês + {num_cuidadoras} cuidadoras + 1 TUI = {num_bebes + num_cuidadoras + 1}")
    print("-" * 78)

    with lock_status:
        soma_pedidos_bebes = sum(b["total_pedidos"] for b in status_bebes.values())
        soma_atendidos_bebes = sum(b["total_atendidos"] for b in status_bebes.values())
        soma_atendidos_cuidadoras = sum(c["total_atendidos"] for c in status_cuidadoras.values())
        bebes_final = {i: dict(b) for i, b in status_bebes.items()}
        cuidadoras_final = {j: dict(c) for j, c in status_cuidadoras.items()}

    with lock_metricas:
        m_final = dict(metricas)

    with lock_atendimentos:
        total_hist_atendimentos = len(atendimentos)
        tempo_medio_espera = (sum(a[2] for a in atendimentos) / total_hist_atendimentos) if total_hist_atendimentos > 0 else 0.0

    pedidos_restantes_fila = len(fila)

    print("BALANÇO DE REQUISIÇÕES:")
    print(f" - Total de pedidos registrados pelos Bebês:        {soma_pedidos_bebes}")
    print(f" - Contador global de pedidos gerados:              {m_final['total_pedidos_gerados']}")
    print(f" - Total de atendimentos registrados pelos Bebês:   {soma_atendidos_bebes}")
    print(f" - Total de atendimentos feitos pelas Cuidadoras:   {soma_atendidos_cuidadoras}")
    print(f" - Histórico de atendimentos registrados (lista):   {total_hist_atendimentos}")
    print(f" - Contador global de atendimentos:                 {m_final['total_pedidos_atendidos']}")
    print(f" - Chamados órfãos / restantes na fila:            {pedidos_restantes_fila}")
    
    if total_hist_atendimentos > 0:
        print(f" - Tempo médio de espera até atendimento:          {tempo_medio_espera:4.2f}s")
    print("-" * 78)

    print("EFICÁCIA DOS DISPOSITIVOS DE SINCRONIZAÇÃO (CONCEITOS DE S.O.):")
    print(f" 1. Exclusão Mútua na Fila (Condition Variable / Monitor):     {m_final['conflitos_fila_pop']} conflitos")
    print("    -> Cuidadoras e bebês sincronizados via Fila escalonada com Condition Variable.")

    print(f" 2. Integridade na Leitura da Interface TUI/GUI (Locks):       {m_final['erros_concorrencia_tui']} leituras corrompidas")
    print("    -> RLock protegeu os dicionários de status contra leituras sujas e conflitos de iteração.")

    print(" 3. Notificação Direta Bebê-Cuidadora (Events / Sinalização):")
    print("    -> Fim da espera ocupada (busy waiting) dos bebês ao aguardar atendimento.")

    print(f" 4. Ocorrências de Inanição (Starvation > {LIMITE_STARVATION}s): {m_final['total_starvations']}")
    print("    -> Bebês monitorados e atendidos de forma coordenada e thread-safe.")

    # Verificação de Discrepância / Lost Updates
    discrepancia = abs(soma_atendidos_bebes - soma_atendidos_cuidadoras)
    if discrepancia == 0 and (m_final['total_pedidos_gerados'] == soma_pedidos_bebes) and (m_final['total_pedidos_atendidos'] == soma_atendidos_cuidadoras):
        print(" 5. Consistência dos Contadores Compartilhados:")
        print("    -> Nenhuma discrepância detectada! Somas locais e globais perfeitamente consistentes.")
        print("       (Evidência da eliminação de Lost Updates através de Locks/Mutex nos contadores).")
    else:
        print(" 5. Discrepância nos Contadores Compartilhados:")
        print(f"    -> Diferença entre contagens locais e globais: {discrepancia}")

    print("-" * 78)
    print("TABELA INDIVIDUAL DOS BEBÊS:")
    for i in range(num_bebes):
        b = bebes_final[i]
        print(f" - Bebê #{b['id']:02d}: {b['total_pedidos']} pedido(s) gerado(s) | "
              f"{b['total_atendidos']} atendido(s) | {b['starvation_count']} episódio(s) de inanição")

    print("\nTABELA INDIVIDUAL DAS CUIDADORAS:")
    for j in range(num_cuidadoras):
        c = cuidadoras_final[j]
        print(f" - Cuidadora #{c['id']:02d}: {c['total_atendidos']} atendimento(s) realizado(s)")

    print("=" * 78 + "\n")


# ==============================================================================
# DISPARO DAS THREADS E CONTROLE DA SIMULAÇÃO
# ==============================================================================
def main():
    global rodando

    print(f"Iniciando simulação sincronizada com {num_bebes} bebês, {num_cuidadoras} cuidadoras por {tempo_simulacao}s [política: {politica}]...")
    time.sleep(1.0)

    threads_bebes = []
    for i in range(num_bebes):
        t = threading.Thread(target=rotina_bebe, args=(i,), daemon=True)
        threads_bebes.append(t)
        t.start()

    threads_cuidadoras = []
    for j in range(num_cuidadoras):
        t = threading.Thread(target=rotina_cuidadora, args=(j,), daemon=True)
        threads_cuidadoras.append(t)
        t.start()

    thread_tui = threading.Thread(target=rotina_tui, daemon=True)
    thread_tui.start()

    # Thread principal aguarda o tempo de simulação
    try:
        time.sleep(tempo_simulacao)
    except KeyboardInterrupt:
        print("\n\nSimulação interrompida pelo usuário via Ctrl+C!")

    # Sinaliza encerramento para todas as threads
    rodando = False

    # Desbloqueia threads aguardando em filas e eventos
    fila.notify_all()
    for ev in eventos_atendido.values():
        ev.set()

    # Aguarda as threads finalizarem
    for t in threads_bebes + threads_cuidadoras:
        t.join(timeout=1.0)
    thread_tui.join(timeout=1.0)

    # Exibe o relatório final
    exibir_relatorio_final()


if __name__ == "__main__":
    main()
