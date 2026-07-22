interface CameraPreviewProps {
  frame: string | null;
  onClose: () => void;
}

function CameraPreview({ frame, onClose }: CameraPreviewProps) {
  if (!frame) return null;

  return (
    <div className="absolute bottom-3 right-3 z-40 animate-fade-in">
      <div className="relative w-[240px] h-[160px] rounded-lg overflow-hidden border border-sirius-border bg-black/60 shadow-lg">
        <img
          src={`data:image/jpeg;base64,${frame}`}
          alt="Camera"
          className="w-full h-full object-cover"
        />
        <div className="absolute top-1 left-1.5 flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
          <span className="text-[9px] font-mono font-bold text-white/80 drop-shadow">
            CAMERA
          </span>
        </div>
        <button
          onClick={onClose}
          className="absolute top-1 right-1.5 w-4 h-4 flex items-center justify-center rounded bg-black/40 hover:bg-black/70 text-white/70 hover:text-white text-[10px] leading-none transition-colors"
        >
          X
        </button>
      </div>
    </div>
  );
}

export default CameraPreview;
