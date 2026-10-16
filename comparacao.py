#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Baby Threads - Comparação entre políticas de escalonamento e modos de sincronização
Disciplina: Sistemas Operacionais (C12) - Inatel

Roda a mesma simulação do baby-threads.py (sem alterá-la) para cada combinação de
política (fifo, sjf, priority) e modo (sync, sem-sync), várias vezes e em diferentes
cargas, e compara desempenho e problemas de concorrência em tabelas. Os resultados
por execução também vão para um CSV.

Uso:
    python comparacao.py                                  # varredura padrão: 3 cenários de carga
    python comparacao.py <BEBES> <CUIDADORAS> <TEMPO> [REPETICOES]
Exemplo:
    python comparacao.py 12 2 20 5
"""

import csv
import importlib.util
import os
import statistics
import sys
import threading
import time

from escalonamento import NECESSIDADES, POLITICAS

DIRETORIO = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_SIMULACAO = os.path.join(DIRETORIO, "baby-threads.py")
ARQUIVO_CSV = os.path.join(DIRETORIO, "comparacao_resultados.csv")

TEMPO_PADRAO = 20
REPETICOES_PADRAO = 5

# (nome, bebês, cuidadoras): da folga à sobrecarga
CENARIOS_PADRAO = [
    ("Folga", 4, 3),
    ("Equilibrado", 6, 2),
    ("Sobrecarga", 12, 2),
]

# (rótulo, passa --sem-sync ao baby-threads.py)
MODOS = [("sync", False), ("sem-sync", True)]

# Cada caso é uma (política, modo)
CASOS = [(p, m) for m, _ in MODOS for p in POLITICAS]

# (chave, cabeçalho, formato, melhor): "min"/"max" marca o melhor valor com *
COLUNAS = [
    ("atendidos", "Atendidos", "{:.1f}", "max"),
    ("espera_media", "Espera méd.", "{:.2f}s", "min"),
    ("espera_p95", "Espera p95", "{:.2f}s", "min"),
    ("espera_max", "Espera máx.", "{:.2f}s", "min"),
    ("starvations", "Starvations", "{:.1f}", "min"),
    ("mortes_bebes", "Mortes de bebês", "{:.1f}", "min"),
    ("pendentes", "Fila final", "{:.1f}", "min"),
    ("utilizacao", "Utilização", "{:.0%}", None),
]

COLUNAS_CONCORRENCIA = [
    ("conflitos_fila", "Conflitos na fila"),
    ("contadores_divergentes", "Contadores divergentes"),
]


def exibir_ajuda():
    print("\nUso: python comparacao.py [<NUM_BEBES> <NUM_CUIDADORAS> <TEMPO_SIMULACAO> [REPETICOES]]")
    print("Sem argumentos, roda a varredura padrão (Folga, Equilibrado, Sobrecarga).")
    print("Exemplo: python comparacao.py 12 2 20 5\n")
    sys.exit(1)


# ==============================================================================
# EXECUÇÃO DA SIMULAÇÃO
# ==============================================================================
def carregar_simulacao(num_bebes, num_cuidadoras, tempo, politica, sem_sync):
    """Carrega o baby-threads.py como um módulo novo, com os argumentos do caso."""
    argv_original = sys.argv
    sys.argv = [ARQUIVO_SIMULACAO, str(num_bebes), str(num_cuidadoras), str(tempo), politica]
    if sem_sync:
        sys.argv.append("--sem-sync")
    try:
        nome = f"baby_threads_{politica}_{'sem' if sem_sync else 'com'}_sync"
        spec = importlib.util.spec_from_file_location(nome, ARQUIVO_SIMULACAO)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
    finally:
        sys.argv = argv_original
    return modulo


def duracao_media(tipo):
    minimo, maximo = NECESSIDADES[tipo]["duracao"]
    return (minimo + maximo) / 2


def percentil(valores, p):
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(p * len(ordenados)))]


def contar_divergencias(sim, total_atendimentos):
    """
    Soma o quanto contadores que deveriam ser iguais divergem entre si.
    Em modo sincronizado deve ser 0; sem sync, incrementos perdidos (lost updates) aparecem aqui.
    """
    pedidos_bebes = sum(b["total_pedidos"] for b in sim.status_bebes.values())
    atendidos_bebes = sum(b["total_atendidos"] for b in sim.status_bebes.values())
    atendidos_cuidadoras = sum(c["total_atendidos"] for c in sim.status_cuidadoras.values())
    return (abs(sim.metricas["total_pedidos_gerados"] - pedidos_bebes)
            + abs(sim.metricas["total_pedidos_atendidos"] - total_atendimentos)
            + abs(atendidos_bebes - total_atendimentos)
            + abs(atendidos_cuidadoras - total_atendimentos))


def coletar(sim, num_cuidadoras, tempo, fim):
    """Extrai as métricas de uma simulação já encerrada."""
    atendimentos = list(sim.atendimentos)  # (bebe_id, tipo, tempo_espera)
    esperas = [a[2] for a in atendimentos]
    pendentes = [fim - p["timestamp"] for p in sim.fila.snapshot()]

    metricas = {
        "atendidos": len(atendimentos),
        "espera_media": statistics.fmean(esperas) if esperas else 0.0,
        "espera_p95": percentil(esperas, 0.95),
        # inclui quem ainda esperava na fila no fim: sem isso a inanição some da conta
        "espera_max": max(esperas + pendentes, default=0.0),
        "starvations": sum(b["starvation_count"] for b in sim.status_bebes.values()),
        # bebês distintos com ao menos um episódio: um bebê só "morre" uma vez
        "mortes_bebes": sum(1 for b in sim.status_bebes.values() if b["starvation_count"] > 0),
        "pendentes": len(pendentes),
        "utilizacao": min(1.0, sum(duracao_media(a[1]) for a in atendimentos) / (num_cuidadoras * tempo)),
        "conflitos_fila": sim.metricas["conflitos_fila_pop"],
        "contadores_divergentes": contar_divergencias(sim, len(atendimentos)),
    }
    for tipo in NECESSIDADES:
        do_tipo = [a[2] for a in atendimentos if a[1] == tipo]
        metricas[f"espera_{tipo}"] = statistics.fmean(do_tipo) if do_tipo else None
    return metricas


def executar_repeticao(num_bebes, num_cuidadoras, tempo):
    """Roda todos os casos ao mesmo tempo, para pegarem o mesmo período de relógio."""
    sem_sync_de = dict(MODOS)
    sims = {
        (politica, modo): carregar_simulacao(num_bebes, num_cuidadoras, tempo, politica, sem_sync_de[modo])
        for politica, modo in CASOS
    }

    threads = []
    for sim in sims.values():
        for i in range(num_bebes):
            threads.append(threading.Thread(target=sim.rotina_bebe, args=(i,), daemon=True))
        for j in range(num_cuidadoras):
            threads.append(threading.Thread(target=sim.rotina_cuidadora, args=(j,), daemon=True))
    for t in threads:
        t.start()

    time.sleep(tempo)
    fim = time.time()
    for sim in sims.values():
        sim.rodando = False
    for t in threads:
        t.join(timeout=2.5)

    return {caso: coletar(sim, num_cuidadoras, tempo, fim) for caso, sim in sims.items()}


# ==============================================================================
# AGREGAÇÃO E APRESENTAÇÃO
# ==============================================================================
def media_de(execucoes, chave):
    valores = [e[chave] for e in execucoes if e[chave] is not None]
    return statistics.fmean(valores) if valores else None


def prefixo(caso):
    politica, modo = caso
    return f"{modo:<10}{politica:<10}"


def imprimir_tabela_desempenho(resultados):
    print("Desempenho (o * marca o melhor valor entre as políticas do mesmo modo):")
    larg = {chave: max(13, len(nome) + 2) for chave, nome, _, _ in COLUNAS}
    cabecalho = f"{'Modo':<10}{'Política':<10}" + "".join(f"{nome:>{larg[chave]}}" for chave, nome, _, _ in COLUNAS)
    print(cabecalho)
    print("-" * len(cabecalho))

    medias = {c: {k: media_de(resultados[c], k) for k, _, _, _ in COLUNAS} for c in CASOS}
    for modo, _ in MODOS:
        do_modo = [(p, modo) for p in POLITICAS]
        for caso in do_modo:
            linha = prefixo(caso)
            for chave, _, formato, melhor in COLUNAS:
                valor = medias[caso][chave]
                texto = formato.format(valor)
                if melhor:
                    todos = [round(medias[q][chave], 2) for q in do_modo]
                    alvo = max(todos) if melhor == "max" else min(todos)
                    if max(todos) != min(todos) and round(valor, 2) == alvo:
                        texto += "*"
                linha += f"{texto:>{larg[chave]}}"
            print(linha)
        print()


def imprimir_efeito_sincronizacao(resultados):
    print("Efeito da sincronização, por política (Δ = sem-sync em relação a sync):")
    colunas = ["Atend. sync", "Atend. sem", "Espera sync", "Espera sem", "Δ espera"]
    larguras = [14, 14, 14, 14, 20]
    cabecalho = f"{'Política':<10}" + "".join(f"{c:>{w}}" for c, w in zip(colunas, larguras))
    print(cabecalho)
    print("-" * len(cabecalho))
    for politica in POLITICAS:
        com = resultados[(politica, "sync")]
        sem = resultados[(politica, "sem-sync")]
        atend_com, atend_sem = media_de(com, "atendidos"), media_de(sem, "atendidos")
        esp_com, esp_sem = media_de(com, "espera_media"), media_de(sem, "espera_media")
        # o percentual sozinho engana quando a espera base é minúscula, então vai junto com os segundos
        relativo = f"{(esp_sem - esp_com) / esp_com:+.0%}" if esp_com >= 0.05 else "n/d"
        delta = f"{esp_sem - esp_com:+.2f}s ({relativo})"
        valores = [f"{atend_com:.1f}", f"{atend_sem:.1f}", f"{esp_com:.2f}s", f"{esp_sem:.2f}s", delta]
        print(f"{politica:<10}" + "".join(f"{v:>{w}}" for v, w in zip(valores, larguras)))


def imprimir_concorrencia(resultados):
    print("\nProblemas de concorrência (média por execução):")
    cabecalho = f"{'Modo':<10}{'Política':<10}" + "".join(f"{nome:>24}" for _, nome in COLUNAS_CONCORRENCIA)
    print(cabecalho)
    print("-" * len(cabecalho))
    for caso in CASOS:
        linha = prefixo(caso)
        for chave, _ in COLUNAS_CONCORRENCIA:
            linha += f"{media_de(resultados[caso], chave):>24.1f}"
        print(linha)


def imprimir_por_tipo(resultados):
    print("\nEspera média por tipo de necessidade (prioridade 1 = mais urgente):")
    cabecalho = f"{'Modo':<10}{'Política':<10}"
    for tipo, info in NECESSIDADES.items():
        rotulo = tipo + " (p" + str(info["prioridade"]) + ")"
        cabecalho += f"{rotulo:>16}"
    print(cabecalho)
    print("-" * len(cabecalho))
    for caso in CASOS:
        linha = prefixo(caso)
        for tipo in NECESSIDADES:
            valor = media_de(resultados[caso], f"espera_{tipo}")
            linha += f"{(f'{valor:.2f}s' if valor is not None else '-'):>16}"
        print(linha)


def imprimir_cenario(nome, num_bebes, num_cuidadoras, tempo, reps, resultados):
    titulo = (f"CENÁRIO {nome.upper()}: {num_bebes} bebês, {num_cuidadoras} cuidadoras, "
              f"{tempo}s, {reps} repetição(ões)")
    print("\n" + "=" * 100)
    print(titulo)
    print("=" * 100)
    imprimir_tabela_desempenho(resultados)
    imprimir_efeito_sincronizacao(resultados)
    imprimir_concorrencia(resultados)
    imprimir_por_tipo(resultados)


def salvar_csv(linhas):
    campos = ["cenario", "bebes", "cuidadoras", "tempo", "repeticao", "politica", "modo"]
    campos += [c for c, _, _, _ in COLUNAS]
    campos += [c for c, _ in COLUNAS_CONCORRENCIA]
    campos += [f"espera_{t}" for t in NECESSIDADES]
    with open(ARQUIVO_CSV, "w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(linhas)


# ==============================================================================
# PONTO DE ENTRADA
# ==============================================================================
def main():
    reps = REPETICOES_PADRAO
    tempo = TEMPO_PADRAO
    cenarios = CENARIOS_PADRAO

    if len(sys.argv) in (4, 5):
        try:
            num_bebes, num_cuidadoras, tempo = (int(a) for a in sys.argv[1:4])
            if len(sys.argv) == 5:
                reps = int(sys.argv[4])
            if min(num_bebes, num_cuidadoras, tempo, reps) <= 0:
                raise ValueError()
        except ValueError:
            print("\nErro: todos os parâmetros devem ser inteiros positivos.")
            exibir_ajuda()
        cenarios = [("Personalizado", num_bebes, num_cuidadoras)]
    elif len(sys.argv) != 1:
        exibir_ajuda()

    total = len(cenarios) * reps * tempo
    print(f"Comparando {len(POLITICAS)} políticas ({', '.join(POLITICAS)}) x {len(MODOS)} modos "
          f"({', '.join(m for m, _ in MODOS)}) em {len(cenarios)} cenário(s), "
          f"{reps} repetição(ões) de {tempo}s. Duração estimada: ~{total}s.")
    print("Todos os casos rodam ao mesmo tempo em cada repetição, para pegarem as mesmas condições.")

    linhas_csv = []
    for nome, num_bebes, num_cuidadoras in cenarios:
        print(f"\n>> {nome}: {num_bebes} bebês, {num_cuidadoras} cuidadoras")
        resultados = {caso: [] for caso in CASOS}
        for r in range(1, reps + 1):
            print(f"   repetição {r}/{reps}...", flush=True)
            por_caso = executar_repeticao(num_bebes, num_cuidadoras, tempo)
            for (politica, modo), metricas in por_caso.items():
                resultados[(politica, modo)].append(metricas)
                linhas_csv.append({
                    "cenario": nome, "bebes": num_bebes, "cuidadoras": num_cuidadoras,
                    "tempo": tempo, "repeticao": r, "politica": politica, "modo": modo, **metricas,
                })
        imprimir_cenario(nome, num_bebes, num_cuidadoras, tempo, reps, resultados)

    salvar_csv(linhas_csv)
    print(f"\nResultados por execução salvos em: {ARQUIVO_CSV}\n")


if __name__ == "__main__":
    main()
