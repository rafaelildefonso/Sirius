import { CheckCircle, User, MessageSquare, Shield, Settings } from 'lucide-react';
import type { AssistantProfile, AssistantStyle } from '../../lib/store';

interface StepCompleteProps {
  profile: AssistantProfile;
  onFinish: () => void;
}

const STYLE_LABELS: Record<AssistantStyle, string> = {
  professional: 'Profissional',
  friendly: 'Amigável',
  technical: 'Técnico',
  creative: 'Criativo',
};

export function StepComplete({ profile, onFinish }: StepCompleteProps) {
  const activePermissions = Object.entries(profile.permissions)
    .filter(([_, enabled]) => enabled)
    .map(([key]) => key);

  return (
    <div className="flex flex-col items-center text-center py-6">
      {/* Success Icon */}
      <div
        className="w-20 h-20 rounded-2xl flex items-center justify-center mb-6"
        style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
      >
        <CheckCircle size={36} />
      </div>

      <h2 className="text-2xl font-bold mb-2" style={{ color: 'var(--color-text)' }}>
        Tudo pronto!
      </h2>
      <p className="text-sm mb-6" style={{ color: 'var(--color-text-secondary)' }}>
        Seu assistente está configurado e pronto para ajudar
      </p>

      {/* Resumo das configurações */}
      <div
        className="w-full max-w-sm rounded-xl p-4 mb-6"
        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}
      >
        <h3
          className="text-xs font-semibold uppercase tracking-wider mb-4 text-left"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          Resumo da Configuração
        </h3>

        <div className="space-y-3">
          {/* Nome */}
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
            >
              <User size={16} />
            </div>
            <div className="text-left">
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Usuário
              </p>
              <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                {profile.userName}
              </p>
            </div>
          </div>

          {/* Estilo */}
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
            >
              <MessageSquare size={16} />
            </div>
            <div className="text-left">
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Estilo do Assistente
              </p>
              <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                {STYLE_LABELS[profile.assistantStyle]}
              </p>
            </div>
          </div>

          {/* Permissões */}
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
            >
              <Shield size={16} />
            </div>
            <div className="text-left">
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Permissões Ativas
              </p>
              <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                {activePermissions.length} de 5
              </p>
            </div>
          </div>

          {/* Preferências */}
          <div className="flex items-center gap-3">
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
            >
              <Settings size={16} />
            </div>
            <div className="text-left">
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Idioma
              </p>
              <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                {profile.language === 'pt' ? 'Português' : profile.language === 'en' ? 'English' : 'Español'}
              </p>
            </div>
          </div>
        </div>
      </div>

      <p className="text-xs max-w-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        Você pode alterar todas essas configurações depois em "Configurações" &gt; "Perfil do Assistente"
      </p>
    </div>
  );
}
