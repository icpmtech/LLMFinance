/**
 * **Benchmark de quem vende** — `/benchmark/vendedor`.
 *
 * A leitura é a de quem vive de concursos públicos, e é o espelho da página
 * «Benchmark do comprador»:
 *
 * - o **grafo** radial põe a empresa no centro, os seus **compradores** no
 *   primeiro anel (raio pelo valor que lhe vende, cor pela força/fraqueza da
 *   relação) e os **concorrentes** que vendem a esses mesmos compradores no anel
 *   exterior;
 * - o **mapa OSM** mostra onde já vendeu, e a **tabela** ordena os compradores
 *   pelo peso nas minhas vendas, com a minha quota nas compras de cada um, o meu
 *   preço face à mediana do segmento e quantos fornecedores lhes vendem;
 * - o **detalhe** de cada relação explica o que me favorece (pouca concorrência,
 *   quota alta, preço abaixo da mediana) e o que me prejudica (muitos
 *   concorrentes, quota baixa, preço acima da mediana);
 * - cada empresa aparece com o seu **site e logótipo** (módulo
 *   `/empresas/perfil`), para se reconhecer a marca no grafo e nas listas.
 *
 * Toda a página é o componente partilhado `BenchmarkBuyerPage` com
 * `perspectiva="vendedor"`: o desenho, os menus e as tabelas são os mesmos, só
 * muda o papel do nó central. Os rótulos vêm do servidor (`labels`).
 */
import BenchmarkBuyerPage from "./BenchmarkBuyerPage";

export default function BenchmarkSellerPage({ onSwitchView }: { onSwitchView?: () => void }) {
  return <BenchmarkBuyerPage perspectiva="vendedor" onSwitchView={onSwitchView} />;
}
