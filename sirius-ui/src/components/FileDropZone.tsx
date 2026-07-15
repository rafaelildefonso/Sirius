import { useCallback, useState } from "react";

interface FileDropZoneProps {
  onFileChange: (path: string | null) => void;
}

function FileDropZone({ onFileChange }: FileDropZoneProps) {
  const [dragOver, setDragOver] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) {
        setFileName(file.name);
        // In Tauri, we'd get the real path. For now just name.
        onFileChange((file as any).path ?? file.name);
      }
    },
    [onFileChange]
  );

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`px-3 py-2 border-t border-sirius-border transition-colors cursor-default ${
        dragOver ? "drop-zone-drag-over" : ""
      }`}
    >
      {fileName ? (
        <p className="text-[10px] font-mono text-sirius-green truncate">
          {fileName}
        </p>
      ) : (
        <p className="text-[10px] font-mono text-sirius-text-dim text-center">
          Drop file here
        </p>
      )}
    </div>
  );
}

export default FileDropZone;
