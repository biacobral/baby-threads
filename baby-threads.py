#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baby Threads: Uso de Threads para simulação de um berçário virtual
Disciplina: Sistemas Operacionais (C12) - Inatel

Implementação SEM mecanismos de sincronização.
O objetivo é evidenciar condições de corrida (race conditions), inanição (starvation),
leituras inconsistentes e disputas por recursos compartilhados sem travas (locks/semáforos).
"""

import os
import random
import sys
import threading
import time

# ==============================================================================
# VALIDAÇÃO DOS ARGUMENTOS DE LINHA DE COMANDO
# ==============================================================================
def exibir_ajuda():
    print("\nUso incorreto dos parâmetros.")
    print("Siga o formato: python baby-threads.py <NUM_BEBES> <NUM_CUIDADORAS> <TEMPO_SIMULACAO>")
    print("Exemplo: python baby-threads.py 5 2 15\n")
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

# ==============================================================================
# RECURSOS COMPARTILHADOS (ESTRITAMENTE SEM LOCKS / SEMÁFOROS)
# ==============================================================================
# Lista compartilhada de atendimento (fila de requisições sujeita a race conditions)
fila = []

# Histórico compartilhado de atendimentos concluídos (bebe_id, tipo, tempo_espera)
atendimentos = []

# Tipos de necessidades suportadas pelo berçário
TIPOS_NECESSIDADES = ["fome", "fralda", "sono", "higiene"]

def criar_necessidades(bebe_id):
    """Gera um chamado com necessidade aleatória e timestamp de criação."""
    return {
        "bebe_id": bebe_id,
        "tipo": random.choice(TIPOS_NECESSIDADES),
        "timestamp": time.time(),
    }

# Dicionários compartilhados contendo o status de cada entidade
status_bebes = {}
status_cuidadoras = {}

# Métricas globais
metricas = {
    "conflitos_fila_pop": 0,      # IndexError ao tentar retirar da fila (Check-then-act race)
    "erros_concorrencia_tui": 0,  # RuntimeError ou outras exceções por leitura concorrente na TUI
    "total_pedidos_gerados": 0,
    "total_pedidos_atendidos": 0,
    "total_starvations": 0,
}

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
# THREAD DO BEBÊ (PRODUTOR DE DEMANDAS)
# ==============================================================================
def rotina_bebe(bebe_id):
    """
    Simula o ciclo de vida de um bebê:
    1. Brinca ou dorme por um período aleatório;
    2. Sente uma necessidade (fome, fralda, sono, higiene) e começa a chorar;
    3. Insere uma solicitação na fila compartilhada (sem sincronização);
    4. Aguarda até ser atendido por uma cuidadora (ou sofre starvation se demorar).
    """
    global rodando

    while rodando:
        # Estado de repouso / brincadeira
        estado_inicial = random.choice(["BRINCANDO", "DORMINDO"])
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

        status_bebes[bebe_id]["estado"] = "CHORANDO"
        status_bebes[bebe_id]["necessidade"] = necessidade
        status_bebes[bebe_id]["inicio_espera"] = pedido["timestamp"]
        status_bebes[bebe_id]["total_pedidos"] += 1

        # Incremento concorrente no contador global (suscetível a lost updates)
        metricas["total_pedidos_gerados"] += 1

        # Insere na fila compartilhada sem trava
        fila.append(pedido)

        # Espera ser atendido antes de gerar outra necessidade
        sofreu_starvation = False
        while rodando and not status_bebes[bebe_id]["atendido_evento"]:
            espera = time.time() - status_bebes[bebe_id]["inicio_espera"]
            status_bebes[bebe_id]["tempo_espera_atual"] = espera

            # Se a espera passar do limite de paciência, caracteriza inanição (starvation)
            if espera >= LIMITE_STARVATION and not sofreu_starvation:
                sofreu_starvation = True
                status_bebes[bebe_id]["starvation_count"] += 1
                metricas["total_starvations"] += 1

            time.sleep(0.05)

        status_bebes[bebe_id]["tempo_espera_atual"] = 0.0


# ==============================================================================
# THREAD DA CUIDADORA (CONSUMIDOR DE DEMANDAS)
# ==============================================================================
def rotina_cuidadora(cuidadora_id):
    """
    Simula o trabalho de uma cuidadora:
    1. Monitora a fila compartilhada em tempo real;
    2. Quando detecta itens, tenta retirar o primeiro da fila (pop(0));
    3. Sem travas, ocorre a condição de corrida clássica (Check-Then-Act):
       duas cuidadoras veem len(fila) > 0, mas a segunda toma IndexError!
    4. Atende a necessidade do bebê por um intervalo de 0.5s a 1.5s;
    5. Libera o bebê e adiciona o evento ao histórico de atendimentos.
    """
    global rodando

    while rodando:
        status_cuidadoras[cuidadora_id]["estado"] = "OCIOSA"
        status_cuidadoras[cuidadora_id]["atendendo_bebe"] = None
        status_cuidadoras[cuidadora_id]["necessidade_atual"] = None

        if len(fila) > 0:
            # JANELA CRÍTICA DA CONDIÇÃO DE CORRIDA:
            # Uma cuidadora vê que há pedidos e caminha até o berço (pequeno delay).
            # Sem sincronização, outra cuidadora pode retirar o mesmo item nesse intervalo!
            time.sleep(random.uniform(0.01, 0.04))

            try:
                # Disputa direta pelo primeiro elemento da fila sem locks
                pedido = fila.pop(0)
            except IndexError:
                # Outra cuidadora foi mais rápida e esvaziou a fila.
                metricas["conflitos_fila_pop"] += 1
                continue
            except Exception:
                metricas["conflitos_fila_pop"] += 1
                continue

            bebe_id = pedido["bebe_id"]
            necessidade = pedido["tipo"]
            tempo_espera = time.time() - pedido["timestamp"]

            # Atualiza status sem bloqueio
            status_cuidadoras[cuidadora_id]["estado"] = "ATENDENDO"
            status_cuidadoras[cuidadora_id]["atendendo_bebe"] = bebe_id
            status_cuidadoras[cuidadora_id]["necessidade_atual"] = necessidade

            # Marca o bebê como atendido na visão global
            status_bebes[bebe_id]["estado"] = "SENDO_ATENDIDO"

            # Tempo gasto cuidando do bebê (0.5s a 1.5s)
            tempo_cuidado = random.uniform(0.5, 1.5)
            time.sleep(tempo_cuidado)

            # Conclusão do atendimento e gravação concorrente no histórico
            atendimentos.append((bebe_id, necessidade, tempo_espera))
            status_cuidadoras[cuidadora_id]["total_atendidos"] += 1
            metricas["total_pedidos_atendidos"] += 1
            status_bebes[bebe_id]["total_atendidos"] += 1
            status_bebes[bebe_id]["atendido_evento"] = True
        else:
            time.sleep(0.05)


# ==============================================================================
# THREAD DO VISUALIZADOR TUI (TERMINAL USER INTERFACE)
# ==============================================================================
def rotina_tui():
    """
    Renderiza em tempo real um painel no terminal com o status da simulação.
    Como lê estruturas que estão sendo modificadas em paralelo sem sincronização,
    pode capturar exceções como RuntimeError (tamanho alterado durante iteração).
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

            linhas = []
            linhas.append("\033[H\033[J")  # ANSI escape para limpar a tela e posicionar o cursor
            linhas.append("=" * 78)
            linhas.append("BABY THREADS - BERÇÁRIO VIRTUAL CONCORRENTE".center(78))
            linhas.append("[ MODO SEM SINCRONIZAÇÃO ]".center(78))
            linhas.append("=" * 78)
            linhas.append(f"Tempo: {tempo_decorrido:4.1f}s / {tempo_simulacao:4.1f}s | "
                          f"Bebês: {num_bebes} | Cuidadoras: {num_cuidadoras} | Restante: {tempo_restante:4.1f}s")
            linhas.append(f"Fila ({len(fila_snapshot)} item/itens): {fila_str}")
            linhas.append("-" * 78)

            # Painel dos Bebês
            linhas.append("STATUS DOS BEBÊS:")
            linhas.append("ID   Estado           Necessidade   Espera       Starvations   Atendimentos")
            for i in range(num_bebes):
                b = status_bebes[i]
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
                c = status_cuidadoras[j]
                estado = c["estado"]
                bebe_alvo = f"Bebê #{c['atendendo_bebe']:02d}" if c["atendendo_bebe"] is not None else "-"
                nec = c["necessidade_atual"] if c["necessidade_atual"] else "-"
                atend = c["total_atendidos"]
                linhas.append(f"#{c['id']:02d}  {estado:<15}  {bebe_alvo:<15}  {nec:<13}  {atend}")

            linhas.append("-" * 78)

            # Estatísticas em Tempo Real
            linhas.append("PROBLEMAS DE CONCORRÊNCIA EM TEMPO REAL:")
            linhas.append(f"Conflitos de Corrida na Fila (IndexError):     {metricas['conflitos_fila_pop']}")
            linhas.append(f"Falhas por Concorrência na Leitura da TUI:      {metricas['erros_concorrencia_tui']}")
            linhas.append(f"Ocorrências de Inanição (Starvation > {LIMITE_STARVATION}s): {metricas['total_starvations']}")
            linhas.append(f"Pedidos Gerados: {metricas['total_pedidos_gerados']} | Atendidos: {metricas['total_pedidos_atendidos']} | Fila Residual: {len(fila_snapshot)}")
            linhas.append("=" * 78)

            sys.stdout.write("\n".join(linhas) + "\n")
            sys.stdout.flush()

        except (RuntimeError, IndexError, KeyError):
            # Leitura concorrente sofreu inconsistência
            metricas["erros_concorrencia_tui"] += 1
        except Exception:
            metricas["erros_concorrencia_tui"] += 1

        time.sleep(0.25)


# ==============================================================================
# RELATÓRIO FINAL
# ==============================================================================
def exibir_relatorio_final():
    print("\n" + "=" * 78)
    print("RELATÓRIO FINAL DA SIMULAÇÃO".center(78))
    print("=" * 78)
    print(f"Duração configurada: {tempo_simulacao}s")
    print(f"Total de Threads Criadas: {num_bebes} bebês + {num_cuidadoras} cuidadoras + 1 TUI = {num_bebes + num_cuidadoras + 1}")
    print("-" * 78)

    # Métricas globais
    soma_pedidos_bebes = sum(b["total_pedidos"] for b in status_bebes.values())
    soma_atendidos_bebes = sum(b["total_atendidos"] for b in status_bebes.values())
    soma_atendidos_cuidadoras = sum(c["total_atendidos"] for c in status_cuidadoras.values())
    pedidos_restantes_fila = len(fila)

    print("BALANÇO DE REQUISIÇÕES:")
    print(f" - Total de pedidos registrados pelos Bebês:        {soma_pedidos_bebes}")
    print(f" - Contador global de pedidos gerados:              {metricas['total_pedidos_gerados']}")
    print(f" - Total de atendimentos registrados pelos Bebês:   {soma_atendidos_bebes}")
    print(f" - Total de atendimentos feitos pelas Cuidadoras:   {soma_atendidos_cuidadoras}")
    print(f" - Histórico de atendimentos registrados (lista):   {len(atendimentos)}")
    print(f" - Contador global de atendimentos:                 {metricas['total_pedidos_atendidos']}")
    print(f" - Chamados órfãos / restantes na fila:            {pedidos_restantes_fila}")
    
    if atendimentos:
        tempo_medio_espera = sum(a[2] for a in atendimentos) / len(atendimentos)
        print(f" - Tempo médio de espera até atendimento:          {tempo_medio_espera:4.2f}s")
    print("-" * 78)

    print("IMPACTO DA AUSÊNCIA DE SINCRONIZAÇÃO (CONCEITOS DE S.O.):")
    print(f" 1. Condições de Corrida na Fila (IndexError):     {metricas['conflitos_fila_pop']}")
    print("    -> Cuidadoras disputaram simultaneamente o mesmo item e tentaram pop(0)")
    print("       em uma fila já esvaziada pela concorrente (Check-Then-Act Race Condition).")

    print(f" 2. Conflitos de Concorrência na Interface TUI:     {metricas['erros_concorrencia_tui']}")
    print("    -> Leitura das estruturas enquanto bebês e cuidadoras gravavam dados sem travas.")

    print(f" 3. Ocorrências de Inanição (Starvation):          {metricas['total_starvations']}")
    print(f"    -> Bebês que esperaram mais de {LIMITE_STARVATION}s chorando sem atendimento imediato.")

    # Verificação de Discrepância / Lost Updates
    discrepancia = abs(soma_atendidos_bebes - soma_atendidos_cuidadoras)
    if discrepancia > 0 or (metricas['total_pedidos_gerados'] != soma_pedidos_bebes):
        print(" 4. Discrepância nos Contadores Compartilhados:")
        print(f"    -> Diferença entre contagens locais e globais: {discrepancia}")
        print("       (Evidência clara de Lost Updates por operações de incremento não-atômicas!)")
    else:
        print(" 4. Discrepância nos Contadores Compartilhados: Nenhuma detectada nas somas finais.")

    print("-" * 78)
    print("TABELA INDIVIDUAL DOS BEBÊS:")
    for i in range(num_bebes):
        b = status_bebes[i]
        print(f" - Bebê #{b['id']:02d}: {b['total_pedidos']} pedido(s) gerado(s) | "
              f"{b['total_atendidos']} atendido(s) | {b['starvation_count']} episódio(s) de inanição")

    print("\nTABELA INDIVIDUAL DAS CUIDADORAS:")
    for j in range(num_cuidadoras):
        c = status_cuidadoras[j]
        print(f" - Cuidadora #{c['id']:02d}: {c['total_atendidos']} atendimento(s) realizado(s)")

    print("=" * 78 + "\n")


# ==============================================================================
# DISPARO DAS THREADS E CONTROLE DA SIMULAÇÃO
# ==============================================================================
def main():
    global rodando

    print(f"Iniciando simulação com {num_bebes} bebês, {num_cuidadoras} cuidadoras por {tempo_simulacao}s...")
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

    # Aguarda as threads finalizarem
    for t in threads_bebes + threads_cuidadoras:
        t.join(timeout=1.0)
    thread_tui.join(timeout=1.0)

    # Exibe o relatório final
    exibir_relatorio_final()


if __name__ == "__main__":
    main()

