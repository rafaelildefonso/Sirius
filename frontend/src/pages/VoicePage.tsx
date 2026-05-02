import { useEffect, useState } from 'react';
import { Mic, MicOff, ArrowLeft, X } from 'lucide-react';
import { Button } from '../components/ui/button';
import { invoke } from '@tauri-apps/api/core';
import { isTauri } from '../lib/api';

export function VoicePage() {
  const [status, setStatus] = useState<'idle' | 'recording' | 'processing' | 'playing'>('idle');
  const [subtitle, setSubtitle] = useState('');
  const [orbPulse, setOrbPulse] = useState(0);

  // Simulate voice assistant states
  useEffect(() => {
    const interval = setInterval(() => {
      setOrbPulse((prev) => (prev + 0.1) % (Math.PI * 2));
    }, 50);
    return () => clearInterval(interval);
  }, []);

  const handleClose = async () => {
    if (isTauri()) {
      // Close voice mode and reopen main window
      await invoke('close_voice_mode');
    }
  };

  const orbSize = status === 'recording' ? 80 : status === 'processing' ? 100 : 120;
  const pulseSize = orbSize + Math.sin(orbPulse) * (status === 'playing' ? 20 : 8);

  const getStatusText = () => {
    switch (status) {
      case 'idle':
        return '';
      case 'recording':
        return 'ouvindo';
      case 'processing':
        return 'pensando';
      case 'playing':
        return '';
    }
  };

  const getOrbColor = () => {
    switch (status) {
      case 'idle':
        return '#00a8ff';
      case 'recording':
        return '#5cd6ff';
      case 'processing':
        return '#5cd6ff';
      case 'playing':
        return '#00a8ff';
    }
  };

  const handlePushToTalk = () => {
    if (status === 'idle') {
      setStatus('recording');
      setSubtitle('');
    } else if (status === 'recording') {
      setStatus('processing');
      // Simulate processing
      setTimeout(() => {
        setStatus('playing');
        setSubtitle('Estou aqui para ajudar!');
        // Simulate playback end
        setTimeout(() => {
          setStatus('idle');
          setSubtitle('');
        }, 3000);
      }, 1500);
    } else if (status === 'playing') {
      // Interrupt
      setStatus('recording');
      setSubtitle('');
    }
  };

  return (
    <div className="fixed inset-0 bg-[#0a0a0a] flex flex-col items-center justify-center">
      {/* Close button */}
      <Button
        variant="ghost"
        className="absolute top-4 right-4 text-gray-400 hover:text-white flex items-center gap-2 z-10"
        onClick={handleClose}
      >
        <X className="w-6 h-6" />
        <span>Fechar</span>
      </Button>

      {/* Orb */}
      <div className="relative mb-10">
        <svg width="300" height="300" viewBox="0 0 300 300">
          <circle
            cx="150"
            cy="150"
            r={pulseSize}
            fill={getOrbColor()}
            className="transition-all duration-75"
          />
        </svg>
      </div>

      {/* Subtitle */}
      <div className="text-center max-w-3xl px-8 mb-6">
        <p className="text-2xl text-gray-200 min-h-[2rem]">{subtitle}</p>
      </div>

      {/* Status */}
      <p className="text-lg text-gray-500 mb-12">{getStatusText()}</p>

      {/* Push to talk button */}
      <button
        onMouseDown={handlePushToTalk}
        onMouseUp={() => status === 'recording' && handlePushToTalk()}
        onTouchStart={handlePushToTalk}
        onTouchEnd={() => status === 'recording' && handlePushToTalk()}
        className={`
          w-20 h-20 rounded-full flex items-center justify-center
          transition-all duration-200
          ${status === 'recording' 
            ? 'bg-red-500 scale-110' 
            : 'bg-[#00a8ff] hover:bg-[#0088cc]'
          }
        `}
      >
        {status === 'recording' ? (
          <MicOff className="w-8 h-8 text-white" />
        ) : (
          <Mic className="w-8 h-8 text-white" />
        )}
      </button>

      <p className="mt-4 text-sm text-gray-600">
        {status === 'idle' ? 'Segure para falar' : status === 'recording' ? 'Solte para processar' : ''}
      </p>

      {/* Instructions */}
      <div className="absolute bottom-8 right-8 text-sm text-gray-600">
        ESPAÇO = Falar • ESC = Sair
      </div>
    </div>
  );
}
