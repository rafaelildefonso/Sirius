import { useState } from 'react';
import { StepWelcome } from './StepWelcome';
import { StepStyle } from './StepStyle';
import { StepPermissions } from './StepPermissions';
import { StepPreferences } from './StepPreferences';
import { StepComplete } from './StepComplete';
import { useAppStore, type AssistantProfile, type AssistantStyle, type Language } from '../../lib/store';

type WizardStep = 'welcome' | 'style' | 'permissions' | 'preferences' | 'complete';

const STEPS: WizardStep[] = ['welcome', 'style', 'permissions', 'preferences', 'complete'];

interface OnboardingWizardProps {
  onComplete: () => void;
}

export function OnboardingWizard({ onComplete }: OnboardingWizardProps) {
  const [step, setStep] = useState<WizardStep>('welcome');
  const { assistantProfile, updateAssistantProfile, completeOnboarding, exportProfileToFile } = useAppStore();
  const [formData, setFormData] = useState<AssistantProfile>(assistantProfile);

  const currentStepIndex = STEPS.indexOf(step);
  const progress = ((currentStepIndex + 1) / STEPS.length) * 100;

  const updateField = <K extends keyof AssistantProfile>(
    field: K,
    value: AssistantProfile[K]
  ) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const updatePermission = (key: keyof AssistantProfile['permissions'], value: boolean) => {
    setFormData((prev) => ({
      ...prev,
      permissions: { ...prev.permissions, [key]: value },
    }));
  };

  const handleNext = () => {
    // Salvar progresso atual no store
    updateAssistantProfile(formData);

    const nextIndex = currentStepIndex + 1;
    if (nextIndex < STEPS.length) {
      setStep(STEPS[nextIndex]);
    }
  };

  const handleBack = () => {
    const prevIndex = currentStepIndex - 1;
    if (prevIndex >= 0) {
      setStep(STEPS[prevIndex]);
    }
  };

  const handleSkip = () => {
    // Usar valores padrão e pular direto para o fim
    handleFinish();
  };

  const handleFinish = () => {
    // Salvar todos os dados e marcar como completo
    const finalProfile = { ...formData, onboardingCompleted: true };
    updateAssistantProfile(finalProfile);
    completeOnboarding();
    
    // Export profile to file for voice assistant to read
    // Small delay to ensure profile is saved first
    setTimeout(() => {
      exportProfileToFile();
      console.log('[Onboarding] Profile exported for voice assistant');
    }, 100);
    
    onComplete();
  };

  const canProceed = () => {
    switch (step) {
      case 'welcome':
        return formData.userName.trim().length > 0;
      default:
        return true;
    }
  };

  return (
    <div
      className="fixed inset-0 flex items-center justify-center z-50"
      style={{ background: 'var(--color-bg)' }}
    >
      <div
        className="w-full max-w-2xl mx-6 rounded-2xl overflow-hidden flex flex-col"
        style={{
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
          maxHeight: '90vh',
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        {/* Header com progresso */}
        <div className="px-8 pt-8 pb-4">
          <div className="flex items-center justify-between mb-4">
            <h1 className="text-xl font-bold" style={{ color: 'var(--color-text)' }}>
              Configuração do Assistente
            </h1>
            <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              {currentStepIndex + 1} de {STEPS.length}
            </span>
          </div>

          {/* Barra de progresso */}
          <div
            className="h-1.5 rounded-full overflow-hidden"
            style={{ background: 'var(--color-bg-tertiary)' }}
          >
            <div
              className="h-full rounded-full transition-all duration-300"
              style={{
                background: 'var(--color-accent)',
                width: `${progress}%`,
              }}
            />
          </div>

          {/* Step indicators */}
          <div className="flex items-center justify-between mt-3">
            {STEPS.map((s, i) => (
              <div
                key={s}
                className="flex flex-col items-center gap-1"
              >
                <div
                  className="w-2.5 h-2.5 rounded-full transition-colors"
                  style={{
                    background:
                      i <= currentStepIndex
                        ? 'var(--color-accent)'
                        : 'var(--color-border)',
                  }}
                />
              </div>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-8 py-4">
          {step === 'welcome' && (
            <StepWelcome
              userName={formData.userName}
              onChange={(name: string) => updateField('userName', name)}
            />
          )}
          {step === 'style' && (
            <StepStyle
              selectedStyle={formData.assistantStyle}
              onChange={(style: AssistantStyle) => updateField('assistantStyle', style)}
            />
          )}
          {step === 'permissions' && (
            <StepPermissions
              permissions={formData.permissions}
              onChange={updatePermission}
            />
          )}
          {step === 'preferences' && (
            <StepPreferences
              language={formData.language}
              theme={formData.theme}
              notifications={formData.notifications}
              fontSize={formData.fontSize}
              onLanguageChange={(lang: Language) => updateField('language', lang)}
              onThemeChange={(theme: 'light' | 'dark' | 'system') => updateField('theme', theme)}
              onNotificationsChange={(val: boolean) => updateField('notifications', val)}
              onFontSizeChange={(size: 'small' | 'default' | 'large') => updateField('fontSize', size)}
            />
          )}
          {step === 'complete' && (
            <StepComplete
              profile={formData}
              onFinish={handleFinish}
            />
          )}
        </div>

        {/* Footer com botões */}
        <div
          className="px-8 py-6 flex items-center justify-between"
          style={{ borderTop: '1px solid var(--color-border)' }}
        >
          <div>
            {step !== 'welcome' && step !== 'complete' && (
              <button
                onClick={handleBack}
                className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                Voltar
              </button>
            )}
          </div>

          <div className="flex items-center gap-3">
            {step !== 'complete' && (
              <button
                onClick={handleSkip}
                className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                Pular
              </button>
            )}

            {step === 'complete' ? (
              <button
                onClick={handleFinish}
                className="px-6 py-2.5 rounded-lg text-sm font-semibold transition-colors"
                style={{
                  background: 'var(--color-accent)',
                  color: 'var(--color-on-accent)',
                }}
              >
                Começar a Usar
              </button>
            ) : (
              <button
                onClick={handleNext}
                disabled={!canProceed()}
                className="px-6 py-2.5 rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
                style={{
                  background: 'var(--color-accent)',
                  color: 'var(--color-on-accent)',
                }}
              >
                {step === 'preferences' ? 'Revisar' : 'Continuar'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
