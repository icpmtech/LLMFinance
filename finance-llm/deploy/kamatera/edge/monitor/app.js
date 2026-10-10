/* Painel de estado do sistema.
 *
 * Construido com `document.createElement` em vez de `innerHTML`: os nomes de
 * contentores, imagens e as mensagens de erro do Docker vem de fora e nao devem
 * ser interpretados como HTML.
 */

'use strict';

const INTERVALO = 5000;

let temporizador = null;

// ------------------------------------------------------------------ utils ---
function el(tag, atributos = {}, filhos = []) {
    const no = document.createElement(tag);
    for (const [chave, valor] of Object.entries(atributos)) {
        if (chave === 'classe') no.className = valor;
        else if (chave === 'texto') no.textContent = valor;
        else no.setAttribute(chave, valor);
    }
    for (const filho of [].concat(filhos)) {
        if (filho != null) no.append(filho);
    }
    return no;
}

function selo(texto, classe) {
    return el('span', { classe: `selo ${classe}`, texto });
}

function formatarTamanho(mb) {
    if (mb == null) return '—';
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
    return `${mb} MB`;
}

/* O `StartedAt` do Docker traz nanosegundos (`...T08:19:59.123456789Z`); o
 * `Date` do browser so aceita ate aos milissegundos. Cortar o resto. */
function desde(iso) {
    if (!iso) return '—';
    const limpo = String(iso).replace(/(\.\d{3})\d+/, '$1');
    const t = Date.parse(limpo);
    if (Number.isNaN(t)) return '—';

    const segundos = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (segundos < 60) return `${segundos} s`;
    const minutos = Math.floor(segundos / 60);
    if (minutos < 60) return `${minutos} min`;
    const horas = Math.floor(minutos / 60);
    if (horas < 24) return `${horas} h ${minutos % 60} min`;
    return `${Math.floor(horas / 24)} d ${horas % 24} h`;
}

function quandoCarimbo(segundos) {
    if (!segundos) return '—';
    return new Date(segundos * 1000).toLocaleString('pt-PT');
}

/* Classe do selo conforme a saude/estado. */
function classeEstado(estado, saude) {
    if (estado !== 'running') return 'mau';
    if (saude === 'healthy') return 'bom';
    if (saude === 'unhealthy') return 'mau';
    if (saude === 'starting') return 'atencao';
    return 'neutro';
}

// --------------------------------------------------------------- entrada ----
const ecraEntrada = document.getElementById('entrada');
const ecraPainel = document.getElementById('painel');
const formEntrada = document.getElementById('form-entrada');
const campoPassword = document.getElementById('password');
const botaoEntrar = document.getElementById('botao-entrar');
const erroEntrada = document.getElementById('erro-entrada');

function mostrarEntrada(mensagem) {
    ecraPainel.hidden = true;
    ecraEntrada.hidden = false;
    if (mensagem) {
        erroEntrada.textContent = mensagem;
        erroEntrada.hidden = false;
    } else {
        erroEntrada.hidden = true;
    }
    pararAtualizacao();
    campoPassword.value = '';
    campoPassword.focus();
}

function mostrarPainel() {
    ecraEntrada.hidden = true;
    ecraPainel.hidden = false;
    carregar();
    arrancarAtualizacao();
}

formEntrada.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    botaoEntrar.disabled = true;
    erroEntrada.hidden = true;
    try {
        const resposta = await fetch('api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: campoPassword.value }),
        });
        const dados = await resposta.json().catch(() => ({}));
        if (!resposta.ok) {
            mostrarEntrada(dados.erro || `não foi possível entrar (HTTP ${resposta.status})`);
            return;
        }
        campoPassword.value = '';
        mostrarPainel();
    } catch (erro) {
        mostrarEntrada(`falha de rede: ${erro.message}`);
    } finally {
        botaoEntrar.disabled = false;
    }
});

// ---------------------------------------------------------------- painel ----
const cartoes = document.getElementById('cartoes');
const corpoServicos = document.querySelector('#tabela-servicos tbody');
const corpoImagens = document.querySelector('#tabela-imagens tbody');
const contagemServicos = document.getElementById('contagem-servicos');
const contagemImagens = document.getElementById('contagem-imagens');
const contexto = document.getElementById('contexto');
const atualizado = document.getElementById('atualizado');
const aviso = document.getElementById('aviso');

function cartaoDado(rotulo, valor, nota, percentagem) {
    const filhos = [el('div', { classe: 'rotulo', texto: rotulo }),
                    el('div', { classe: 'valor', texto: valor })];
    if (nota) filhos.push(el('div', { classe: 'nota', texto: nota }));
    if (percentagem != null) {
        const classe = percentagem >= 90 ? 'mau' : percentagem >= 75 ? 'atencao' : '';
        filhos.push(el('div', { classe: `barra ${classe}` }, [
            el('i', { style: `width:${Math.min(100, percentagem)}%` }),
        ]));
    }
    return el('div', { classe: 'cartao-dado' }, filhos);
}

function desenharMaquina(maquina, docker) {
    cartoes.replaceChildren();

    if (maquina) {
        const memoria = maquina.memoria || {};
        cartoes.append(cartaoDado(
            'Memória',
            `${memoria.usada_mb ?? '?'} / ${memoria.total_mb ?? '?'} MB`,
            `${memoria.disponivel_mb ?? '?'} MB disponíveis`,
            memoria.percentagem,
        ));

        const swap = maquina.swap || {};
        cartoes.append(cartaoDado(
            'Swap',
            swap.total_mb ? `${swap.usado_mb} / ${swap.total_mb} MB` : 'sem swap',
            swap.total_mb ? `${swap.percentagem}% usado` : '—',
            swap.total_mb ? swap.percentagem : null,
        ));

        const carga = maquina.carga || [0, 0, 0];
        const nucleos = maquina.cpu_nucleos || 1;
        cartoes.append(cartaoDado(
            'Carga',
            carga.map((n) => n.toFixed(2)).join('  '),
            `${nucleos} núcleos · 1/5/15 min`,
            Math.min(100, Math.round((carga[0] / nucleos) * 100)),
        ));

        const disco = maquina.disco;
        cartoes.append(cartaoDado(
            'Disco',
            disco ? `${disco.livre_gb} GB livres` : '—',
            disco ? `de ${disco.total_gb} GB` : '—',
            disco ? disco.percentagem : null,
        ));

        cartoes.append(cartaoDado(
            'No ar há',
            maquina.uptime_h != null ? `${maquina.uptime_h} h` : '—',
            'desde o último arranque',
            null,
        ));
    }

    if (docker && !docker.erro) {
        cartoes.append(cartaoDado(
            'Docker',
            `${docker.em_execucao ?? '?'} / ${docker.contentores ?? '?'}`,
            `${docker.imagens ?? '?'} imagens · Docker ${docker.versao ?? '?'}`,
            null,
        ));
    }
}

function desenharServicos(servicos) {
    corpoServicos.replaceChildren();
    if (!servicos.length) {
        corpoServicos.append(el('tr', {}, [
            el('td', { colspan: '7', classe: 'fraca', texto: 'sem contentores' }),
        ]));
        contagemServicos.textContent = '';
        return;
    }

    let emFalha = 0;
    for (const c of servicos) {
        const saudavel = c.estado === 'running'
            && c.saude !== 'unhealthy'
            && !(c.sondas || []).some((s) => !s.ok);
        if (!saudavel) emFalha += 1;

        const celulaPortas = el('div', { classe: 'portas' });
        for (const p of c.portas || []) {
            celulaPortas.append(el('span', { classe: 'porta', texto: `${p.host}→${p.interna}` }));
        }
        for (const s of c.sondas || []) {
            celulaPortas.append(el('span', {
                classe: `porta ${s.ok ? 'ok' : 'mau'}`,
                texto: s.ok ? `${s.porta} ${s.codigo} ${s.ms}ms` : `${s.porta} sem resposta`,
                title: s.erro || `HTTP ${s.codigo}`,
            }));
        }
        if (!(c.portas || []).length) {
            celulaPortas.append(el('span', { classe: 'fraca', texto: '—' }));
        }

        corpoServicos.append(el('tr', {}, [
            el('td', { classe: 'nome', texto: c.nome }),
            el('td', { classe: 'fraca', texto: c.imagem || '—' }),
            el('td', {}, [selo(c.estado || '?', c.estado === 'running' ? 'bom' : 'mau')]),
            el('td', {}, [c.saude ? selo(c.saude, classeEstado(c.estado, c.saude)) : el('span', { classe: 'fraca', texto: '—' })]),
            el('td', { classe: 'num', texto: desde(c.iniciado) }),
            el('td', { classe: 'num', texto: c.reinicios != null ? String(c.reinicios) : '—' }),
            el('td', {}, [celulaPortas]),
        ]));
    }

    contagemServicos.textContent = `${servicos.length} contentores`
        + (emFalha ? ` · ${emFalha} com problemas` : ' · todos saudáveis');
}

function desenharImagens(imagens) {
    corpoImagens.replaceChildren();
    contagemImagens.textContent = `${imagens.length} imagens`;

    for (const i of imagens) {
        const tags = el('div', { classe: 'portas' });
        for (const t of i.tags) {
            tags.append(el('span', {
                classe: `porta ${i.sem_tag ? 'mau' : ''}`,
                texto: i.sem_tag ? 'sem tag' : t,
            }));
        }
        corpoImagens.append(el('tr', {}, [
            el('td', {}, [tags]),
            el('td', { classe: 'num', texto: formatarTamanho(i.tamanho_mb) }),
            el('td', { classe: 'fraca', texto: quandoCarimbo(i.criada) }),
            el('td', { classe: 'num', texto: String(i.contentores ?? 0) }),
        ]));
    }
}

async function carregar() {
    try {
        const resposta = await fetch('api/estado', { cache: 'no-store' });
        if (resposta.status === 401) {
            mostrarEntrada('A sessão expirou. Entre outra vez.');
            return;
        }
        if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
        const estado = await resposta.json();

        const erros = [];
        if (estado.docker && estado.docker.erro) erros.push(`Docker: ${estado.docker.erro}`);
        if (estado.erro_servicos) erros.push(`Serviços: ${estado.erro_servicos}`);
        if (estado.erro_imagens) erros.push(`Imagens: ${estado.erro_imagens}`);
        aviso.hidden = erros.length === 0;
        aviso.textContent = erros.join(' · ');

        desenharMaquina(estado.maquina, estado.docker);
        desenharServicos(estado.servicos || []);
        desenharImagens(estado.imagens || []);

        contexto.textContent = estado.docker && estado.docker.erro
            ? 'a falar com o Docker sem sucesso'
            : 'contentores, imagens e máquina desta VM';
        atualizado.textContent = `atualizado às ${new Date().toLocaleTimeString('pt-PT')}`;
    } catch (erro) {
        aviso.hidden = false;
        aviso.textContent = `não consegui ler o estado: ${erro.message}`;
        atualizado.textContent = '';
    }
}

function arrancarAtualizacao() {
    pararAtualizacao();
    // Com o separador em segundo plano nao vale a pena sondar o servidor.
    temporizador = setInterval(() => {
        if (!document.hidden) carregar();
    }, INTERVALO);
}

function pararAtualizacao() {
    if (temporizador) clearInterval(temporizador);
    temporizador = null;
}

// ----------------------------------------------------------------- acoes ----
document.getElementById('botao-atualizar').addEventListener('click', carregar);

document.getElementById('botao-sair').addEventListener('click', async () => {
    try {
        await fetch('api/logout', { method: 'POST' });
    } catch (erro) {
        /* sair localmente mesmo que o pedido falhe */
    }
    mostrarEntrada(null);
});

document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !ecraPainel.hidden) carregar();
});

// ------------------------------------------------------------------ inicio --
(async function inicio() {
    try {
        const resposta = await fetch('api/sessao', { cache: 'no-store' });
        const dados = await resposta.json();
        if (dados.autenticado) mostrarPainel();
        else mostrarEntrada(null);
    } catch (erro) {
        mostrarEntrada(null);
    }
})();
