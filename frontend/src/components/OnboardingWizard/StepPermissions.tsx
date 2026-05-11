import { FileText, Terminal, Globe, Plug, Bot, AlertTriangle } from 'lucide-react';
import type { AssistantProfile } from '../../lib/store';

interface PermissionOption {
  key: keyof AssistantProfile['permissions'];
  label: string;
  description: string;
  icon: typeof FileText;
  warning?: string;
}

const PERMISSION_OPTIONS: PermissionOption[] = [
  {
    key: 'fileAccess',
    label: 'Acesso a Arquivos Locais',
    description: 'Ler documentos, notas, código e outros arquivos do seu sistema',
    icon: FileText,
  },
  {
    key: 'commandExecution',
    label: 'Execução de Comandos',
    description: 'Rodar scripts, instalar dependências e executar comandos no terminal',
    icon: Terminal,
    warning: 'Use com cautela - o assistente pode executar comandos no seu sistema',
  },
  {
    key: 'internetAccess',
    label: 'Acesso à Internet',
    description: 'Buscar informações atualizadas e acessar APIs online',
    icon: Globe,
  },
  {
    key: 'externalIntegrations',
    label: 'Integrações Externas',
    description: 'Conectar com Gmail, Slack, Notion e outras plataformas',
    icon: Plug,
  },
  {
    key: 'autonomousMode',
    label: 'Modo Autônomo',
    description: 'Executar tarefas complexas sem pedir confirmação prévia',
    icon: Bot,
    warning: 'O assistente tomará decisões automaticamente - recomendado apenas para usuários avançados',
  },
];

interface StepPermissionsProps {
  permissions: AssistantProfile['permissions'];
  onChange: (key: keyof AssistantProfile['permissions'], value: boolean) => void;
}

export function StepPermissions({ permissions, onChange }: StepPermissionsProps) {
  return (
    <div className="py-4">
      <h2 className="text-xl font-bold mb-2 text-center" style={{ color: 'var(--color-text)' }}>
        Níveis de Permissão
      </h2>
      <p className="text-sm text-center mb-6" style={{ color: 'var(--color-text-secondary)' }}>
        Defina o que o assistente pode fazer no seu sistema
      </p>

      <div className="space-y-3">
        {PERMISSION_OPTIONS.map((option) => {
          const isEnabled = permissions[option.key];
          const Icon = option.icon;

          return (
            <div
              key={option.key}
              className="p-4 rounded-xl transition-all"
              style={{
                background: isEnabled ? 'var(--color-accent-subtle)' : 'var(--color-bg)',
                border: `1px solid ${isEnabled ? 'var(--color-accent)' : 'var(--color-border)'}`,
              }}
            >
              <div className="flex items-start gap-4">
                <div
                  className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                  style={{
                    background: isEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                    color: isEnabled ? 'white' : 'var(--color-text-tertiary)',
                  }}
                >
                  <Icon size={20} />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <h3
                      className="font-semibold text-sm"
                      style={{ color: isEnabled ? 'var(--color-accent)' : 'var(--color-text)' }}
                    >
                      {option.label}
                    </h3>

                    <button
                      onClick={() => onChange(option.key, !isEnabled)}
                      className="relative w-12 h-6 rounded-full transition-colors"
                      style={{
                        background: isEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                      }}
                    >
                      <span
                        className="absolute top-1 w-4 h-4 rounded-full bg-white transition-all"
                        style={{
                          left: isEnabled ? 'calc(100% - 1.25rem)' : '0.25rem',
                        }}
                      />
                    </button>
                  </div>

                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                    {option.description}
                  </p>

                  {option.warning && isEnabled && (
                    <div
                      className="flex items-start gap-2 mt-2 p-2 rounded-lg"
                      style={{
                        background: 'rgba(234, 179, 8, 0.1)',
                        border: '1px solid rgba(234, 179, 8, 0.3)',
                      }}
                    >
                      <AlertTriangle size={14} style={{ color: '#eab308', flexShrink: 0 }} />
                      <p className="text-xs" style={{ color: '#eab308' }}>
                        {option.warning}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-xs text-center mt-4" style={{ color: 'var(--color-text-tertiary)' }}>
        Você pode alterar essas permissões a qualquer momento nas configurações
      </p>
    </div>
  );
}
