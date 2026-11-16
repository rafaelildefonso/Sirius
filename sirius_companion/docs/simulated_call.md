# Ligação simulada do Sirius

Esse recurso mostra uma tela de chamada dentro do aplicativo. Ele não inicia
uma ligação telefônica e não usa a permissão de chamadas do Android.

## Padrões escolhidos

- A ligação toca por até 30 segundos. Se não houver resposta, ela é encerrada e
  não é repetida.
- Uma recusa explícita agenda outra tentativa depois de 5 minutos. São no
  máximo 3 tentativas para a mesma ocorrência, contando a primeira.
- Aceitar inicia a fala do Android em português do Brasil. O texto inclui o
  título, horário e observações disponíveis. Aceitar não conclui a tarefa.
- A tela é silenciosa. Fora do Não Perturbe, o aplicativo pode vibrar; durante
  o Não Perturbe, não há som ou vibração e a recusa não agenda outra tentativa.
- Se o Android não permitir consultar o estado do Não Perturbe, o Sirius
  considera o modo ativo por segurança. O app oferece um atalho para a permissão
  especial do Android.

## Alertas do Android

O app solicita permissão de notificações, alarmes exatos e intenção de tela
cheia quando o sistema oferece esses controles. Se a tela cheia estiver
bloqueada, o lembrete usa uma notificação silenciosa que precisa ser tocada
para abrir a tela. Sem permissão de alarmes exatos, o alerta pode atrasar. Sem
permissão de notificações, o Android pode não mostrar o fallback.

O Android 14 e versões posteriores limitam a tela cheia a usos de chamadas e
despertadores. A permissão também pode depender da política da loja e das
configurações do aparelho. Por isso, a tela de criação/edição informa quando o
fallback será uma notificação.

## Persistência, tarefas e Rotina

A preferência por tarefa, o número de recusas e o horário da próxima tentativa
ficam no banco local; a preferência também é enviada ao Sirius no PC. Concluir,
editar ou reagendar uma tarefa cancela o alerta atual e limpa a próxima
tentativa. A tela de Rotina mantém definições e ocorrências no banco local. Cada
ocorrência tem um identificador estável por rotina e data; pausar ou excluir a
rotina cancela as ocorrências futuras e preserva as já concluídas. Os quatro
avisos da rotina são: nenhum, notificação silenciosa, alarme e ligação simulada.
A ligação da rotina usa as mesmas regras e a mesma tela usadas pelas tarefas.

`SimulatedCallService` concentra a fala e a consulta ao Não Perturbe.
`SimulatedCallPolicy` contém os intervalos e as regras de repetição. `AlarmScreen`
aceita callbacks para aceitar, recusar e encerrar sem resposta.

## Limitações conhecidas

O app ainda não oferece uma ação para excluir uma tarefa avulsa. A sincronização
de tarefas também não transporta tombstones de tarefas removidas diretamente no
PC; por isso, uma chamada já agendada no celular pode permanecer até o estado do
PC convergir por outra atualização. A exclusão/pausa de rotinas feitas no
celular cancela os alertas locais futuros, mas exclusões feitas no PC não são
propagadas ao app como tombstones.

As garantias de silêncio, vibração, tela cheia e pontualidade dependem das
permissões e das restrições de bateria do Android. Elas precisam ser verificadas
em aparelhos reais e em diferentes fabricantes.
