import React, { useEffect, useRef } from 'react';

/**
 * AudioDomeVisualizer
 * A high-performance canvas visualizer rendering a dotted wave/dome across the bottom of the screen.
 *
 * Requirements:
 * - Neutral grey when idle
 * - Glowing teal when bot is speaking or candidate is talking
 * - Subtle motion / phase wave while "thinking"
 * - Dome-shaped contour (center higher than flanks)
 * - Dot columns reacting dynamically to audio level
 */
export default function AudioDomeVisualizer({
  status = 'idle',
  audioLevel = 0,
  className = '',
}) {
  const canvasRef = useRef(null);
  const animFrameRef = useRef(null);
  const smoothedLevelRef = useRef(0);
  const phaseRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let width = (canvas.width = canvas.parentElement?.clientWidth || window.innerWidth);
    let height = (canvas.height = canvas.parentElement?.clientHeight || 200);

    const handleResize = () => {
      if (!canvas || !canvas.parentElement) return;
      width = canvas.width = canvas.parentElement.clientWidth;
      height = canvas.height = canvas.parentElement.clientHeight;
    };
    window.addEventListener('resize', handleResize);

    const isSpeakingOrTalking =
      status === 'speaking' ||
      status === 'talking' ||
      (status === 'listening' && audioLevel > 0.08);
    const isThinking = status === 'thinking';

    const render = () => {
      // Smooth interpolation of audio level
      const targetLevel = Math.max(0, Math.min(1, audioLevel));
      smoothedLevelRef.current += (targetLevel - smoothedLevelRef.current) * 0.18;
      const curLevel = smoothedLevelRef.current;

      // Increment phase for thinking/ambient motion
      const phaseSpeed = isThinking ? 0.045 : isSpeakingOrTalking ? 0.03 : 0.012;
      phaseRef.current += phaseSpeed;
      const phase = phaseRef.current;

      ctx.clearRect(0, 0, width, height);

      // Visual styling parameters based on state
      const isTeal = isSpeakingOrTalking || (status === 'listening' && curLevel > 0.05);

      const numCols = Math.max(28, Math.min(64, Math.floor(width / 22)));
      const colSpacing = width / (numCols + 1);
      const dotsPerCol = 10;
      const baseDomeHeight = height * 0.42;

      for (let c = 0; c < numCols; c++) {
        const x = (c + 1) * colSpacing;
        const normalizedX = (c / (numCols - 1)) * 2 - 1; // -1 to 1
        const domeArch = Math.max(0, 1 - Math.pow(normalizedX, 2)); // Parabolic dome profile

        // Column dynamic height:
        // - dome arch profile
        // - audio level modulation
        // - thinking ripple wave
        let colDynamicFactor = 0;
        if (isThinking) {
          colDynamicFactor = Math.sin(phase * 1.5 + c * 0.35) * 0.22 + 0.15;
        } else if (isTeal) {
          const colWave = Math.sin(phase * 2.5 + c * 0.4) * 0.15;
          colDynamicFactor = curLevel * 0.85 + colWave * curLevel;
        } else {
          // Ambient gentle breathing
          colDynamicFactor = Math.sin(phase + c * 0.2) * 0.05;
        }

        const maxColHeight = baseDomeHeight * (domeArch * 0.8 + 0.2) * (1 + colDynamicFactor * 1.4);
        const colBottom = height - 12;

        for (let r = 0; r < dotsPerCol; r++) {
          const rowFrac = (r + 1) / dotsPerCol; // 0 to 1 upwards
          const y = colBottom - rowFrac * maxColHeight;

          // Dot size & alpha based on row position and state
          const dotRadius = isTeal
            ? 1.8 + rowFrac * 1.6 + curLevel * 0.6
            : isThinking
            ? 1.5 + rowFrac * 1.2
            : 1.2 + rowFrac * 1.0;

          let alpha = 0;
          if (isTeal) {
            // Bright vibrant teal with luminous upper crest
            alpha = (0.35 + rowFrac * 0.55) * Math.min(1, 0.4 + curLevel * 1.2);
            ctx.fillStyle = `rgba(45, 212, 191, ${alpha.toFixed(3)})`; // Teal 400
            ctx.shadowColor = 'rgba(20, 184, 166, 0.6)';
            ctx.shadowBlur = 6;
          } else if (isThinking) {
            // Subtle energetic amber/teal phase motion
            alpha = 0.25 + Math.sin(phase * 2 + c * 0.3 + r * 0.2) * 0.25;
            ctx.fillStyle = `rgba(94, 234, 212, ${Math.max(0.1, alpha).toFixed(3)})`;
            ctx.shadowColor = 'rgba(45, 212, 191, 0.3)';
            ctx.shadowBlur = 4;
          } else {
            // Neutral idle grey
            alpha = 0.18 + rowFrac * 0.35;
            ctx.fillStyle = `rgba(161, 161, 170, ${alpha.toFixed(3)})`; // Zinc 400
            ctx.shadowBlur = 0;
          }

          ctx.beginPath();
          ctx.arc(x, y, Math.max(0.8, dotRadius), 0, Math.PI * 2);
          ctx.fill();
        }
      }

      animFrameRef.current = requestAnimationFrame(render);
    };

    animFrameRef.current = requestAnimationFrame(render);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      window.removeEventListener('resize', handleResize);
    };
  }, [status, audioLevel]);

  return (
    <div
      data-testid="audio-dome-visualizer"
      className={`pointer-events-none absolute bottom-0 left-0 right-0 h-44 md:h-56 select-none overflow-hidden ${className}`}
    >
      <canvas ref={canvasRef} className="h-full w-full block" />
      {/* Subtle floor gradient for depth */}
      <div className="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black via-black/60 to-transparent pointer-events-none" />
    </div>
  );
}
