import { Briefcase, Heart, Code, Lightbulb, Check } from 'lucide-react';
import type { AssistantStyle } from '../../lib/store';

interface StyleOption {
  id: AssistantStyle;
  label: string;
  description: string;
  icon: typeof Briefcase;
  preview: string;
}

const STYLE_OPTIONS: StyleOption[] = [
  {
    id: 'professional',
    label: 'Profissional',
    description: 'Tom formal, eficiente, focado em produtividade',
    icon: Briefcase,
    preview: 'Compreendido. Vou analisar seus dados e apresentar um relatório estruturado com as principais métricas.',
  },
  {
    id: 'friendly',
    label: 'Amigável',
    description: 'Tom casual, acolhedor, conversa leve',
    icon: Heart,
    preview: 'Claro! Vou dar uma olhada nisso pra você. Logo trago as informações de forma simples e direta.',
  },
  {
    id: 'technical',
    label: 'Técnico',
    description: 'Preciso, detalhado, focado em dados',
    icon: Code,
    preview: 'Iniciando análise técnica. Processando parâmetros: [OK], compilando estrutura de dados em 3 camadas...',
  },
  {
    id: 'creative',
    label: 'Criativo',
    description: 'Inspirador, brainstorm, pensamento fora da caixa',
    icon: Lightbulb,
    preview: 'Interessante! Que tal explorarmos por um ângulo diferente? Tenho algumas ideias inovadoras para compartilhar.',
  },
];

interface StepStyleProps {
  selectedStyle: AssistantStyle;
  onChange: (style: AssistantStyle) => void;
}

export function StepStyle({ selectedStyle, onChange }: StepStyleProps) {
  return (
    <div className="py-4">
      <h2 className="text-xl font-bold mb-2 text-center" style={{ color: 'var(--color-text)' }}>
        Estilo do Assistente
      </h2>
      <p className="text-sm text-center mb-6" style={{ color: 'var(--color-text-secondary)' }}>
        Escolha como você prefere que o assistente se comunique
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {STYLE_OPTIONS.map((option) => {
          const isSelected = selectedStyle === option.id;
          const Icon = option.icon;

          return (
            <button
              key={option.id}
              onClick={() => onChange(option.id)}
              className="relative p-4 rounded-xl text-left transition-all"
              style={{
                background: isSelected ? 'var(--color-accent-subtle)' : 'var(--color-bg)',
                border: `2px solid ${isSelected ? 'var(--color-accent)' : 'var(--color-border)'}`,
              }}
            >
              {isSelected && (
                <div
                  className="absolute top-3 right-3 w-5 h-5 rounded-full flex items-center justify-center"
                  style={{ background: 'var(--color-accent)' }}
                >
                  <Check size={12} color="white" />
                </div>
              )}

              <div className="flex items-start gap-3">
                <div
                  className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                  style={{
                    background: isSelected ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                    color: isSelected ? 'white' : 'var(--color-text-tertiary)',
                  }}
                >
                  <Icon size={20} />
                </div>

                <div className="flex-1 min-w-0">
                  <h3
                    className="font-semibold text-sm mb-1"
                    style={{ color: isSelected ? 'var(--color-accent)' : 'var(--color-text)' }}
                  >
                    {option.label}
                  </h3>
                  <p className="text-xs mb-3" style={{ color: 'var(--color-text-secondary)' }}>
                    {option.description}
                  </p>
                </div>
              </div>

              {/* Preview */}
              <div
                className="mt-3 p-3 rounded-lg text-xs italic"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text-secondary)',
                  borderLeft: `3px solid ${isSelected ? 'var(--color-accent)' : 'var(--color-border)'}`,
                }}
              >
                "{option.preview}"
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
