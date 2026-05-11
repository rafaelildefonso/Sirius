import { Sparkles, User } from 'lucide-react';

interface StepWelcomeProps {
  userName: string;
  onChange: (name: string) => void;
}

export function StepWelcome({ userName, onChange }: StepWelcomeProps) {
  return (
    <div className="flex flex-col items-center text-center py-8">
      {/* Icon */}
      <div
        className="w-20 h-20 rounded-2xl flex items-center justify-center mb-6"
        style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
      >
        <Sparkles size={36} />
      </div>

      <h2 className="text-2xl font-bold mb-3" style={{ color: 'var(--color-text)' }}>
        Bem-vindo ao Sirius!
      </h2>

      <p className="text-sm max-w-sm mb-8" style={{ color: 'var(--color-text-secondary)' }}>
        Vamos configurar seu assistente pessoal de IA. 
        Estas configurações ajudam o assistente a se adaptar ao seu estilo e necessidades.
      </p>

      {/* Input de nome */}
      <div className="w-full max-w-sm">
        <label
          className="block text-sm font-medium mb-2 text-left"
          style={{ color: 'var(--color-text)' }}
        >
          Como devo te chamar?
        </label>
        <div
          className="flex items-center gap-3 px-4 py-3 rounded-xl"
          style={{
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
          }}
        >
          <User size={18} style={{ color: 'var(--color-text-tertiary)' }} />
          <input
            type="text"
            value={userName}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Seu nome"
            className="flex-1 bg-transparent outline-none text-sm"
            style={{ color: 'var(--color-text)' }}
            autoFocus
          />
        </div>
        {userName.trim().length === 0 && (
          <p className="text-xs mt-2 text-left" style={{ color: 'var(--color-text-tertiary)' }}>
            Digite seu nome para continuar
          </p>
        )}
      </div>
    </div>
  );
}
