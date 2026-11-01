/**
 * A small live render of the active receptor, for the sidebar target card.
 *
 * It draws the real deposited coordinates, not an illustration, and reuses the
 * same chain colouring as the main viewer so the thumbnail and the workspace
 * never disagree about what is TERT, what is RNA and what is DNA.
 *
 * The coordinate file is a few megabytes, so the fetch is shared: whichever of
 * this component or MolecularViewer asks first does the download, and the other
 * awaits the same promise.
 */

import React, { useEffect, useRef, useState } from 'react';
import * as $3Dmol from '3dmol';

const TERT = '#59C9C0'; // chains A, C, F, G
const RNA = '#A79BEE'; // chain B
const DNA = '#E9A76A'; // chain D
const LIGAND = '#F2F6F7'; // BIBR1532, comp id 55C

/**
 * 3Dmol's published types declare selector fields as plain strings, but the
 * library accepts arrays at runtime and the main viewer depends on that. Rather
 * than widen the viewer to `any`, name the narrow surface this component uses.
 */
type Selector = Record<string, unknown>;
type Style = Record<string, unknown>;
interface Viewer {
  addModel(data: string, format: string): void;
  setStyle(sel: Selector, style: Style): void;
  zoomTo(): void;
  zoom(factor: number): void;
  render(): void;
  spin(axis: string | false, speed?: number): void;
  clear(): void;
}

let coordinates: Promise<string> | null = null;

/** Fetch the structure once per page load, whoever asks first. */
export function loadStructure(url: string): Promise<string> {
  if (!coordinates) {
    coordinates = fetch(url).then((r) => {
      if (!r.ok) {
        coordinates = null; // let a later mount retry
        throw new Error(`${r.status} ${r.statusText}`);
      }
      return r.text();
    });
  }
  return coordinates;
}

interface Props {
  url: string;
  /** Stop the idle rotation, e.g. when the card is not visible. */
  spin?: boolean;
  className?: string;
}

export const TargetStructureThumb: React.FC<Props> = ({
  url,
  spin = true,
  className = '',
}) => {
  const host = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading');

  useEffect(() => {
    let cancelled = false;
    let viewer: Viewer | null = null;

    (async () => {
      try {
        const text = await loadStructure(url);
        if (cancelled || !host.current) return;

        const v = $3Dmol.createViewer(host.current, {
          backgroundColor: '#18232D',
          antialias: true,
        }) as unknown as Viewer;
        viewer = v;

        v.addModel(text, url.endsWith('.cif') ? 'cif' : 'pdb');

        // Protein body, then the nucleic acids over it, then the ligand.
        v.setStyle(
          { chain: ['A', 'C', 'F', 'G'] },
          { cartoon: { color: TERT, opacity: 0.92, thickness: 0.3 } }
        );
        v.setStyle({ chain: 'B' }, { cartoon: { color: RNA, opacity: 0.85, thickness: 0.4 } });
        v.setStyle({ chain: 'D' }, { cartoon: { color: DNA, opacity: 0.95, thickness: 0.5 } });
        v.setStyle({ resn: '55C' }, { sphere: { color: LIGAND, scale: 0.42 } });
        v.setStyle({ resn: ['HOH', 'WAT'] }, {});

        v.zoomTo();
        v.zoom(1.25);
        v.render();
        if (spin) v.spin('y', 0.35);

        if (!cancelled) setState('ready');
      } catch {
        if (!cancelled) setState('failed');
      }
    })();

    return () => {
      cancelled = true;
      try {
        viewer?.spin(false);
        viewer?.clear();
      } catch {
        /* the viewer is going away regardless */
      }
    };
  }, [url, spin]);

  return (
    <div
      className={`relative rounded-lg overflow-hidden bg-[#131E27] border border-[#202F3C] ${className}`}
    >
      {/* 3Dmol positions its canvas absolutely, so the host needs to fill. */}
      <div ref={host} className="absolute inset-0 [&_canvas]:!rounded-lg" />

      {state === 'loading' && (
        <div className="absolute inset-0 grid place-items-center">
          <span className="text-[9px] font-mono tracking-wider text-[#4C5E6B] animate-pulse">
            LOADING 9Q14
          </span>
        </div>
      )}
      {state === 'failed' && (
        <div className="absolute inset-0 grid place-items-center px-2">
          <span className="text-[9px] font-mono text-[#7E6A52] text-center leading-tight">
            Coordinates unavailable
          </span>
        </div>
      )}

      {state === 'ready' && (
        <div className="absolute bottom-1 left-1.5 flex items-center gap-1.5 pointer-events-none">
          {[
            [TERT, 'TERT'],
            [RNA, 'TERC'],
            [DNA, 'DNA'],
          ].map(([c, label]) => (
            <span key={label} className="flex items-center gap-[3px]">
              <span className="w-1 h-1 rounded-full" style={{ background: c }} />
              <span className="text-[7px] font-mono text-[#90A4AF]">{label}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

export default TargetStructureThumb;
