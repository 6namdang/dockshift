/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import * as $3Dmol from '3dmol';
import {
  RotateCcw,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Minimize2,
  Play,
  Pause,
  Layers,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Eye,
  EyeOff,
  RefreshCw,
  Compass,
  Crosshair,
  Flame,
  ChevronDown,
  ChevronUp,
  X,
  Sliders,
  HelpCircle
} from 'lucide-react';
import { Protein, ComponentVisibility, SelectedComponentType, Ligand, DockingResult } from '../types/docking';
import { StructureInfoBar } from './StructureInfoBar';
import { PlaygroundChallenge } from './PlaygroundChallenge';
import {
  renderBindingPocket,
  renderInteractions,
  clearArtifacts,
  emptyArtifacts,
  makeLigandSelectable,
  pulseLigand,
  LIGAND_RESN,
  POLAR_CUTOFF,
  VDW_CUTOFF,
  POLAR_COLOR,
  VDW_COLOR,
  type Contact,
  type LigandProbe,
  type ModeArtifacts
} from '../lib/pocketModes';

export type RepresentationType =
  | 'pocket'
  | 'interactions'
  | 'ribbon'
  | 'surface'
  | 'backbone'
  | 'sticks';

interface MolecularViewerProps {
  protein: Protein;
  selectedComponent: SelectedComponentType;
  onSelectComponent: (component: SelectedComponentType) => void;
  visibility: ComponentVisibility;
  onToggleVisibility: (key: keyof ComponentVisibility) => void;
  focusedResidue?: { resi: number; chain: string } | null;
  candidates?: Ligand[];
  selectedCandidateId?: string;
  onSelectCandidate?: (id: string) => void;
  dockingResults?: Record<string, DockingResult>;
  onAddNote?: (
    category: 'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment',
    content: string,
    title?: string
  ) => void;
  onNavigateToTab?: (tab: string) => void;
}

export const MolecularViewer: React.FC<MolecularViewerProps> = ({
  protein,
  selectedComponent,
  onSelectComponent,
  visibility,
  onToggleVisibility,
  focusedResidue,
  candidates = [],
  selectedCandidateId = 'bibr1532',
  onSelectCandidate,
  dockingResults = {},
  onAddNote,
  onNavigateToTab
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<any>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [representation, setRepresentation] = useState<RepresentationType>('pocket');
  const [isSpinning, setIsSpinning] = useState<boolean>(false);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [hoveredResidue, setHoveredResidue] = useState<string | null>(null);
  const [cameraView, setCameraView] = useState<'default' | 'inhibitor' | 'active_site' | 'rna'>('default');

  // Candidate exploration panel state (collapsed by default to maximize 3D viewer space)
  const [isCandidateDrawerOpen, setIsCandidateDrawerOpen] = useState<boolean>(false);

  // Playground beginner challenge state
  const [isChallengeOpen, setIsChallengeOpen] = useState<boolean>(false);

  const defaultDemonstrationCandidates: Ligand[] = [
    {
      id: 'bibr1532',
      name: 'BIBR1532',
      chemicalFormula: 'C21H17NO3',
      molecularWeight: 331.36,
      tag: 'Experimental Ligand',
      targetSite: 'TERT Thumb/Palm Pocket (PDB 9Q14)'
    },
    {
      id: 'mst-312',
      name: 'MST-312',
      chemicalFormula: 'C20H14N2O4',
      molecularWeight: 346.34,
      tag: 'Screened Candidate',
      targetSite: 'TERT Allosteric Pocket'
    },
    {
      id: 'costunolide',
      name: 'Costunolide',
      chemicalFormula: 'C15H20O2',
      molecularWeight: 232.32,
      tag: 'Screened Candidate',
      targetSite: 'TERT Thumb Crevice'
    }
  ];

  const displayedCandidates =
    candidates && candidates.length > 0 ? candidates.slice(0, 4) : defaultDemonstrationCandidates;
  const activeCandidate =
    displayedCandidates.find((c) => c.id === selectedCandidateId) || displayedCandidates[0];

  const illustrativeScore =
    activeCandidate?.id === 'bibr1532'
      ? '-9.1'
      : activeCandidate?.prediction?.predicted_pic50
      ? `-${(activeCandidate.prediction.predicted_pic50 * 1.15).toFixed(1)}`
      : '-8.4';

  const surfaceRef = useRef<any>(null);
  const modeArtifactsRef = useRef<ModeArtifacts>(emptyArtifacts());
  const pocketFramedRef = useRef<boolean>(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [ligandProbe, setLigandProbe] = useState<LigandProbe | null>(null);
  const [modeError, setModeError] = useState<string | null>(null);
  const [showContactLabels, setShowContactLabels] = useState<boolean>(true);
  const [ligandFound, setLigandFound] = useState<boolean>(false);

  // Apply styling based on representation, component selection, and show/hide toggles
  const applyStyles = useCallback(
    (viewer: any, rep: RepresentationType, target: SelectedComponentType, vis: ComponentVisibility) => {
      if (!viewer) return;

      // --- Binding Pocket / Interactions ------------------------------
      // Self-contained modes. Everything they draw comes from the loaded
      // 9Q14 coordinates; nothing is synthesised.
      if (rep === 'pocket' || rep === 'interactions') {
        // Interactions must not move the camera. Pocket frames the ligand
        // only the first time, so later re-renders never undo a rotation.
        const keepView = rep === 'interactions' ? viewer.getView() : null;

        // Split the branches rather than narrowing a union: only the
        // interactions result carries contacts, and `in`-narrowing here
        // widens the property to unknown.
        if (rep === 'pocket') {
          const result = renderBindingPocket(viewer, $3Dmol, modeArtifactsRef.current, {
            focusCamera: !pocketFramedRef.current
          });
          modeArtifactsRef.current = result.artifacts;
          setLigandProbe(result.probe);
          setModeError(result.ok ? null : result.reason ?? 'Mode unavailable.');
          setContacts([]);
          if (result.ok) pocketFramedRef.current = true;
        } else {
          const result = renderInteractions(viewer, $3Dmol, modeArtifactsRef.current, {
            showLabels: showContactLabels
          });
          modeArtifactsRef.current = result.artifacts;
          setLigandProbe(result.probe);
          setModeError(result.ok ? null : result.reason ?? 'Mode unavailable.');
          setContacts(result.contacts);
        }

        if (keepView) {
          viewer.setView(keepView);
          viewer.render();
        }
        return;
      }

      // Leaving the pocket modes: drop their surfaces/shapes/labels.
      modeArtifactsRef.current = clearArtifacts(viewer, modeArtifactsRef.current);

      if (surfaceRef.current) {
        try {
          viewer.removeSurface(surfaceRef.current);
        } catch {
          // ignore
        }
        surfaceRef.current = null;
      }

      viewer.setStyle({}, {});

      // Scientifically meaningful component colors:
      // TERT in cyan: #59C9C0 / #63E6DE
      // Telomerase RNA in violet: #A79BEE
      // Telomeric DNA in gold: #E9A76A / #F5AE65
      // Observed BIBR1532 inhibitor in orange: #FF7D45
      const tertColor = '#59C9C0';
      const rnaColor = '#A79BEE';
      const dnaColor = '#E9A76A';
      const inhibitorColor = '#FF7D45';
      const dimColor = '#15212A';

      // 1. TERT Protein (Chain A, plus auxiliary C, F, G)
      if (vis.showProtein) {
        const isDimmed = target === 'rna' || target === 'dna';
        const color = isDimmed ? dimColor : tertColor;
        const opacity = isDimmed ? 0.2 : 1.0;

        if (rep === 'ribbon') {
          viewer.setStyle(
            { chain: ['A', 'C', 'F', 'G'] },
            { cartoon: { color, opacity, thickness: 0.4 } }
          );
        } else if (rep === 'surface') {
          viewer.setStyle(
            { chain: ['A', 'C', 'F', 'G'] },
            { cartoon: { color, opacity: 0.5 } }
          );
          try {
            if (!isDimmed) {
              surfaceRef.current = viewer.addSurface($3Dmol.SurfaceType.VDW, {
                opacity: 0.35,
                color: '#3E8299'
              }, { chain: 'A' });
            }
          } catch (err) {
            console.warn('Surface generation notice:', err);
          }
        } else if (rep === 'backbone') {
          viewer.setStyle(
            { chain: ['A', 'C', 'F', 'G'] },
            { line: { color, linewidth: 2 } }
          );
        } else if (rep === 'sticks') {
          viewer.setStyle(
            { chain: ['A', 'C', 'F', 'G'] },
            { stick: { color, radius: 0.16, opacity } }
          );
        }
      } else {
        viewer.setStyle({ chain: ['A', 'C', 'F', 'G'] }, {});
      }

      // 2. Telomerase RNA (TERC - Chain B)
      if (vis.showRna) {
        const isDimmed = target === 'tert' || target === 'dna';
        const color = isDimmed ? dimColor : rnaColor;
        const opacity = isDimmed ? 0.2 : 1.0;

        viewer.setStyle(
          { chain: 'B' },
          {
            cartoon: { color, opacity, thickness: 0.65 },
            stick: { color, radius: 0.2, opacity }
          }
        );
      } else {
        viewer.setStyle({ chain: 'B' }, {});
      }

      // 3. Telomeric DNA Substrate (Chain D)
      if (vis.showDna) {
        const isDimmed = target === 'tert' || target === 'rna';
        const color = isDimmed ? dimColor : dnaColor;
        const opacity = isDimmed ? 0.2 : 1.0;

        viewer.setStyle(
          { chain: 'D' },
          {
            cartoon: { color, opacity, thickness: 0.8 },
            stick: { color, radius: 0.28, opacity },
            sphere: { color, scale: 0.26, opacity }
          }
        );
      } else {
        viewer.setStyle({ chain: 'D' }, {});
      }

      // 4. Experimentally Observed BIBR1532 Inhibitor (Comp ID: 55C)
      if (vis.showInhibitor) {
        viewer.setStyle(
          { resn: '55C' },
          {
            stick: { color: inhibitorColor, radius: 0.38, opacity: 1.0 },
            sphere: { color: inhibitorColor, scale: 0.32, opacity: 1.0 }
          }
        );
      } else {
        viewer.setStyle({ resn: '55C' }, {});
      }

      // 5. Highlight Inhibitor Binding Pocket Residues if focused
      if (target === 'inhibitor' || target === 'pocket') {
        viewer.setStyle(
          { chain: 'A', resi: [867, 870, 977, 980, 1012, 1013] },
          {
            stick: { color: '#E9A76A', radius: 0.28, opacity: 1.0 },
            cartoon: { color: '#59C9C0', opacity: 1.0 }
          }
        );
      }

      // Hide solvent / waters
      viewer.setStyle({ resn: ['HOH', 'WAT'] }, {});

      viewer.render();
    },
    [showContactLabels]
  );

  // Fetch coordinates and mount 3Dmol viewer
  const loadStructure = useCallback(async () => {
    if (!containerRef.current) return;
    setIsLoading(true);
    setLoadError(null);

    try {
      if (viewerRef.current) {
        viewerRef.current.clear();
      } else {
        const viewer = $3Dmol.createViewer(containerRef.current, {
          backgroundColor: '#0B1118'
        });
        viewerRef.current = viewer;
      }

      const viewer = viewerRef.current;
      const response = await fetch(protein.structureUrl);
      if (!response.ok) {
        throw new Error(`Failed to load PDB ${protein.pdbId} coordinates (${response.status} ${response.statusText})`);
      }

      const fileData = await response.text();
      viewer.clear();
      viewer.addModel(fileData, 'cif');

      // Diagnostic check of loaded chains and residues
      try {
        const model = viewer.getModel();
        if (model) {
          const atoms = model.selectedAtoms({});
          const chainMap = new Map<string, { count: number; resns: Set<string> }>();
          atoms.forEach((a: any) => {
            const ch = a.chain || 'unknown';
            if (!chainMap.has(ch)) {
              chainMap.set(ch, { count: 0, resns: new Set<string>() });
            }
            const item = chainMap.get(ch)!;
            item.count++;
            if (a.resn) item.resns.add(a.resn);
          });
          const summary = Array.from(chainMap.entries()).map(([ch, info]) => ({
            chain: ch,
            atoms: info.count,
            sampleResidues: Array.from(info.resns).slice(0, 8)
          }));
          console.log('[DockShift Diagnostic] PDB 9Q14 Model Chains:', summary);
        }
      } catch (diagErr) {
        console.warn('[DockShift Diagnostic] Chain analysis notice:', diagErr);
      }

      // Setup hover inspector callback
      viewer.setHoverable(
        {},
        true,
        (atom: any, hover: boolean) => {
          if (hover && atom) {
            let subunitName = `Chain ${atom.chain}`;
            if (atom.resn === '55C' || atom.resn === 'BIB') {
              subunitName = 'BIBR1532 Inhibitor (Observed)';
            } else if (atom.chain === 'A') {
              subunitName = 'TERT Catalytic Subunit (Protein)';
            } else if (atom.chain === 'B') {
              subunitName = 'Telomerase RNA / TERC (RNA)';
            } else if (atom.chain === 'D') {
              subunitName = 'Telomeric DNA Substrate (DNA)';
            } else if (atom.chain === 'C') {
              subunitName = 'Shelterin TPP1 Subunit';
            }
            setHoveredResidue(`${subunitName} • ${atom.resn || ''}${atom.resi || ''} [Atom: ${atom.atom || ''}]`);
          } else {
            setHoveredResidue(null);
          }
        },
        () => setHoveredResidue(null)
      );

      // Setup click selection callback directly in 3D
      viewer.setClickable({}, true, (atom: any) => {
        if (!atom) return;
        if (atom.resn === '55C' || atom.resn === 'BIB') {
          onSelectComponent('inhibitor');
        } else if (atom.chain === 'A') {
          if ([867, 870, 977, 980, 1012, 1013].includes(atom.resi)) {
            onSelectComponent('pocket');
          } else {
            onSelectComponent('tert');
          }
        } else if (atom.chain === 'B') {
          onSelectComponent('terc');
        } else if (atom.chain === 'D') {
          onSelectComponent('dna');
        }
      });

      applyStyles(viewer, representation, selectedComponent, visibility);

      // Gameplay: let the player pick BIBR1532 directly in the 3D view.
      makeLigandSelectable(viewer, (probe) => {
        if (!probe.found) return;
        setLigandProbe(probe);
        setLigandFound(true);
        onSelectComponent('inhibitor');
        pulseLigand(viewer);
      });

      // Make the molecular structure fill 70-80% of visible viewer area
      viewer.zoomTo();
      viewer.zoom(1.4);
      viewer.render();
      setIsLoading(false);
    } catch (err: any) {
      console.error('Molecular viewer load error:', err);
      setLoadError(err?.message || 'Unable to download human telomerase 9Q14 coordinates from RCSB.');
      setIsLoading(false);
    }
  }, [protein, representation, selectedComponent, visibility, onSelectComponent, applyStyles]);

  useEffect(() => {
    loadStructure();

    const handleResize = () => {
      if (viewerRef.current) {
        viewerRef.current.resize();
        viewerRef.current.render();
      }
    };

    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      if (viewerRef.current) {
        viewerRef.current.clear();
      }
    };
  }, [protein.pdbId]);

  useEffect(() => {
    if (viewerRef.current && !isLoading) {
      applyStyles(viewerRef.current, representation, selectedComponent, visibility);
    }
  }, [representation, selectedComponent, visibility, applyStyles, isLoading]);

  useEffect(() => {
    if (viewerRef.current && focusedResidue) {
      viewerRef.current.zoomTo({ chain: focusedResidue.chain, resi: focusedResidue.resi }, 1000);
      viewerRef.current.render();
    }
  }, [focusedResidue]);

  // Center on BIBR1532 inhibitor
  const handleFocusOnInhibitor = () => {
    if (!viewerRef.current) return;
    onSelectComponent('inhibitor');
    setCameraView('inhibitor');
    const viewer = viewerRef.current;

    try {
      viewer.zoomTo({ resn: '55C' }, 1000);
    } catch {
      viewer.zoomTo({ chain: 'A', resi: [867, 870, 977, 980] }, 1000);
    }
    viewer.render();
  };

  const handleResetCamera = () => {
    if (!viewerRef.current) return;
    viewerRef.current.zoomTo();
    viewerRef.current.zoom(1.4);
    viewerRef.current.render();
    setCameraView('default');
  };

  const handleZoom = (delta: number) => {
    if (!viewerRef.current) return;
    viewerRef.current.zoom(delta);
    viewerRef.current.render();
  };

  const toggleSpin = () => {
    if (!viewerRef.current) return;
    const nextSpin = !isSpinning;
    setIsSpinning(nextSpin);
    if (nextSpin) {
      viewerRef.current.spin('y', 1.0);
    } else {
      viewerRef.current.spin(false);
    }
  };

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  return (
    <div className="flex flex-col h-full w-full bg-[#0B1118] text-[#E9F0F3] relative select-none overflow-hidden">
      {/* 1. Structure Info Bar: Sleek and Non-Intrusive */}
      <StructureInfoBar
        protein={protein}
        onFocusInhibitor={handleFocusOnInhibitor}
        onToggleChallenge={() => setIsChallengeOpen((prev) => !prev)}
        isChallengeActive={isChallengeOpen}
      />

      {/* 2. Hero 3D Viewport Canvas */}
      <div className="relative flex-1 w-full h-full overflow-hidden bg-[#0B1118]">
        <div
          ref={containerRef}
          className="w-full h-full cursor-grab active:cursor-grabbing"
          style={{ width: '100%', height: '100%', position: 'absolute', top: 0, left: 0 }}
        />

        {/* Loading Overlay */}
        {isLoading && (
          <div className="absolute inset-0 bg-[#0B1118]/90 backdrop-blur-sm flex flex-col items-center justify-center z-30">
            <div className="w-10 h-10 rounded-full border-2 border-[#202F3C] border-t-[#59C9C0] animate-spin mb-3" />
            <div className="text-sm font-semibold text-[#E9F0F3] tracking-wide">
              Loading Human Telomerase (PDB 9Q14)
            </div>
            <div className="text-xs text-[#90A4AF] mt-1 font-mono">
              Coordinates: RCSB 9Q14.cif (3.0 Å Cryo-EM)
            </div>
          </div>
        )}

        {/* Error Overlay */}
        {loadError && (
          <div className="absolute inset-0 bg-[#0B1118]/95 flex flex-col items-center justify-center p-6 z-30 text-center">
            <div className="w-10 h-10 rounded-full bg-red-950/60 border border-red-800/80 flex items-center justify-center text-red-400 mb-2">
              <AlertCircle className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-semibold text-[#E9F0F3] mb-1">
              Structure Coordinates Notice
            </h3>
            <p className="text-xs text-[#90A4AF] max-w-md mb-3 font-mono">
              {loadError}
            </p>
            <button
              onClick={loadStructure}
              className="px-3 py-1.5 text-xs rounded-lg bg-[#18232D] hover:bg-[#202F3C] text-[#59C9C0] border border-[#59C9C0]/30 transition flex items-center gap-1.5 cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Retry Download</span>
            </button>
          </div>
        )}

        {/* Pocket / Contacts status panel — compact, non-blocking */}
        {(representation === 'pocket' || representation === 'interactions') && !isLoading && (
          <div className="absolute bottom-4 left-4 z-20 max-w-[310px] bg-[#18232D]/92 backdrop-blur-md rounded-2xl border border-[#202F3C] shadow-xl text-[11px] text-[#C7D5DE] overflow-hidden">
            <div className="px-3 py-2 border-b border-[#202F3C] flex items-center justify-between gap-2">
              <span className="font-semibold text-[#E9F0F3]">
                {representation === 'pocket' ? 'Binding pocket' : 'Measured contacts'}
              </span>
              {ligandProbe?.found && (
                <span className="text-[10px] text-[#59C9C0]">
                  {LIGAND_RESN} · {ligandProbe.atomCount} atoms
                </span>
              )}
            </div>

            {modeError ? (
              <div className="px-3 py-2 text-[#F5A3A3]">{modeError}</div>
            ) : representation === 'pocket' ? (
              <div className="px-3 py-2 leading-relaxed">
                Surface is the real pocket lining BIBR1532, selected by distance
                from the ligand in PDB 9Q14 — not by chain assignment.
              </div>
            ) : (
              <div className="px-3 py-2">
                {contacts.length === 0 ? (
                  <div className="text-[#90A4AF]">
                    No heavy-atom contacts within cutoffs.
                  </div>
                ) : (
                  <>
                    <div className="flex items-center gap-3 mb-1.5 text-[10px]">
                      <span className="flex items-center gap-1">
                        <span className="inline-block w-2 h-2 rounded-full" style={{ background: POLAR_COLOR }} />
                        N/O ≤ {POLAR_CUTOFF} Å
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="inline-block w-2 h-2 rounded-full" style={{ background: VDW_COLOR }} />
                        C···C ≤ {VDW_CUTOFF} Å
                      </span>
                    </div>
                    <ul className="max-h-28 overflow-y-auto space-y-0.5 pr-1">
                      {contacts.map((c) => (
                        <li key={`${c.chain}${c.resi}${c.proteinAtom}`}>
                          <button
                            type="button"
                            onClick={() => viewerRef.current?.zoomTo({ chain: c.chain, resi: c.resi }, 600)}
                            className="w-full text-left hover:text-[#E9F0F3] cursor-pointer flex justify-between gap-2"
                            title={`Zoom to ${c.residue}${c.resi}`}
                          >
                            <span>
                              {c.residue}{c.resi}
                              <span className="text-[#6E8495]"> {c.proteinAtom}···{c.ligandAtom}</span>
                            </span>
                            <span style={{ color: c.kind === 'polar' ? POLAR_COLOR : VDW_COLOR }}>
                              {c.distance.toFixed(2)} Å
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                    <label className="flex items-center gap-1.5 mt-2 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={showContactLabels}
                        onChange={(e) => setShowContactLabels(e.target.checked)}
                        className="accent-[#59C9C0] cursor-pointer"
                      />
                      <span>Distance labels</span>
                    </label>
                    <p className="mt-2 text-[10px] text-[#8398A8] leading-snug">
                      Measured heavy-atom separations, not assigned bonds. 9Q14 is
                      3.00 Å cryo-EM, so hydrogens are unresolved and a hydrogen
                      bond cannot be confirmed from these coordinates.
                    </p>
                  </>
                )}
              </div>
            )}
          </div>
        )}

        {/* 3. SIMPLIFIED FLOATING CONTROL STRIP (Top-Right) */}
        <div className="absolute top-4 right-4 z-20 flex items-center gap-1.5 bg-[#18232D]/90 backdrop-blur-md px-2.5 py-1.5 rounded-2xl border border-[#202F3C] shadow-xl text-xs">
          {/* Representation Mode */}
          <div className="flex items-center gap-0.5 bg-[#0B1118]/70 p-0.5 rounded-xl border border-[#202F3C]/50">
            {(['pocket', 'interactions', 'ribbon', 'surface'] as RepresentationType[]).map((rep) => (
              <button
                key={rep}
                onClick={() => setRepresentation(rep)}
                title={`Switch representation to ${rep}`}
                className={`px-2 py-0.5 text-[11px] rounded-lg transition capitalize cursor-pointer ${
                  representation === rep
                    ? 'bg-[#59C9C0] text-[#0B1118] font-semibold shadow-sm'
                    : 'text-[#90A4AF] hover:text-[#E9F0F3]'
                }`}
              >
                {rep === 'pocket' ? 'Pocket' : rep === 'interactions' ? 'Contacts' : rep}
              </button>
            ))}
          </div>

          <div className="w-px h-4 bg-[#202F3C]" />

          {/* Subunit Visibility Toggles */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => onToggleVisibility('showProtein')}
              title={visibility.showProtein ? 'Hide TERT Protein' : 'Show TERT Protein'}
              className={`p-1.5 rounded-lg border text-[10px] font-mono flex items-center gap-1 transition cursor-pointer ${
                visibility.showProtein
                  ? 'bg-[#0B1118] text-[#59C9C0] border-[#59C9C0]/40'
                  : 'bg-[#0B1118] text-[#627783] border-[#202F3C] line-through'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-[#59C9C0]" />
              <span>TERT</span>
            </button>

            <button
              onClick={() => onToggleVisibility('showRna')}
              title={visibility.showRna ? 'Hide Telomerase RNA' : 'Show Telomerase RNA'}
              className={`p-1.5 rounded-lg border text-[10px] font-mono flex items-center gap-1 transition cursor-pointer ${
                visibility.showRna
                  ? 'bg-[#0B1118] text-[#A79BEE] border-[#A79BEE]/40'
                  : 'bg-[#0B1118] text-[#627783] border-[#202F3C] line-through'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-[#A79BEE]" />
              <span>RNA</span>
            </button>

            <button
              onClick={() => onToggleVisibility('showDna')}
              title={visibility.showDna ? 'Hide Telomeric DNA' : 'Show Telomeric DNA'}
              className={`p-1.5 rounded-lg border text-[10px] font-mono flex items-center gap-1 transition cursor-pointer ${
                visibility.showDna
                  ? 'bg-[#0B1118] text-[#E9A76A] border-[#E9A76A]/40'
                  : 'bg-[#0B1118] text-[#627783] border-[#202F3C] line-through'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-[#E9A76A]" />
              <span>DNA</span>
            </button>

            <button
              onClick={() => onToggleVisibility('showInhibitor')}
              title={visibility.showInhibitor ? 'Hide BIBR1532 Inhibitor' : 'Show BIBR1532 Inhibitor'}
              className={`p-1.5 rounded-lg border text-[10px] font-mono flex items-center gap-1 transition cursor-pointer ${
                visibility.showInhibitor
                  ? 'bg-[#0B1118] text-[#FF7D45] border-[#FF7D45]/50 font-bold'
                  : 'bg-[#0B1118] text-[#627783] border-[#202F3C] line-through'
              }`}
            >
              <span className="w-2 h-2 rounded-full bg-[#FF7D45]" />
              <span>BIBR</span>
            </button>
          </div>

          <div className="w-px h-4 bg-[#202F3C]" />

          {/* Camera Controls */}
          <div className="flex items-center gap-0.5">
            <button
              onClick={handleResetCamera}
              title="Reset Camera Framing (Fills 70-80% viewport)"
              className="p-1.5 rounded-lg text-[#90A4AF] hover:text-[#59C9C0] hover:bg-[#0B1118] transition cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={() => handleZoom(1.2)}
              title="Zoom In"
              className="p-1.5 rounded-lg text-[#90A4AF] hover:text-[#E9F0F3] hover:bg-[#0B1118] transition cursor-pointer"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={() => handleZoom(0.85)}
              title="Zoom Out"
              className="p-1.5 rounded-lg text-[#90A4AF] hover:text-[#E9F0F3] hover:bg-[#0B1118] transition cursor-pointer"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={toggleSpin}
              title={isSpinning ? 'Pause Rotation' : 'Auto-Rotate Molecule'}
              className={`p-1.5 rounded-lg transition cursor-pointer ${
                isSpinning ? 'bg-[#59C9C0] text-[#0B1118]' : 'text-[#90A4AF] hover:text-[#59C9C0] hover:bg-[#0B1118]'
              }`}
            >
              {isSpinning ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            </button>

            <button
              onClick={toggleFullscreen}
              title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
              className="p-1.5 rounded-lg text-[#90A4AF] hover:text-[#E9F0F3] hover:bg-[#0B1118] transition cursor-pointer"
            >
              {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>

        {/* 4. Hover Inspector Tooltip */}
        {hoveredResidue && (
          <div className="absolute top-16 left-1/2 -translate-x-1/2 z-20 bg-[#18232D]/95 backdrop-blur-md px-3.5 py-1.5 rounded-full border border-[#202F3C] shadow-lg text-[11px] font-mono text-[#E9F0F3] flex items-center gap-2">
            <Eye className="w-3.5 h-3.5 text-[#59C9C0]" />
            <span>{hoveredResidue}</span>
          </div>
        )}

        {/* 5. PLAYGROUND BEGINNER CHALLENGE CARD (Stage 1-4) */}
        {isChallengeOpen && (
          <PlaygroundChallenge
            selectedComponent={selectedComponent}
            onSelectComponent={onSelectComponent}
            onFocusInhibitor={handleFocusOnInhibitor}
            onAddNote={
              onAddNote ||
              ((_cat, _cont, _title) => console.log('Note saved from challenge'))
            }
            onNavigateToTab={onNavigateToTab}
            candidates={candidates}
            isOpen={isChallengeOpen}
            onClose={() => setIsChallengeOpen(false)}
          />
        )}

        {/* 6. UNOBTRUSIVE COMPONENT LEGEND (Bottom-Right) */}
        <div className="absolute bottom-4 right-4 z-10 bg-[#18232D]/80 backdrop-blur-md px-3 py-1.5 rounded-xl border border-[#202F3C] shadow-md text-[11px] font-mono flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-[#59C9C0]" />
            <span className="text-[#E9F0F3]">TERT</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-[#A79BEE]" />
            <span className="text-[#A79BEE]">TERC</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-[#E9A76A]" />
            <span className="text-[#E9A76A]">DNA</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-[#FF7D45]" />
            <span className="text-[#FF7D45] font-semibold">BIBR1532</span>
          </div>
        </div>

        {/* 7. COMPACT COLLAPSIBLE CANDIDATE EXPLORATION DRAWER (Bottom-Left) */}
        <div className="absolute bottom-4 left-4 z-20">
          {!isCandidateDrawerOpen ? (
            <button
              onClick={() => setIsCandidateDrawerOpen(true)}
              className="bg-[#18232D]/90 backdrop-blur-md px-3 py-1.5 rounded-xl border border-[#202F3C] hover:border-[#59C9C0]/40 shadow-lg text-xs flex items-center gap-2 text-[#90A4AF] hover:text-[#E9F0F3] transition cursor-pointer"
            >
              <Sliders className="w-3.5 h-3.5 text-[#59C9C0]" />
              <span>Candidate Selection (Demonstration Data)</span>
              <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[#0B1118] text-[#59C9C0]">
                {activeCandidate?.name}
              </span>
              <ChevronUp className="w-3.5 h-3.5" />
            </button>
          ) : (
            <div className="bg-[#18232D]/95 backdrop-blur-md p-3.5 rounded-2xl border border-[#202F3C] shadow-2xl max-w-lg w-[460px] space-y-2.5 text-xs">
              <div className="flex items-center justify-between pb-1 border-b border-[#202F3C]">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-[#E9F0F3]">
                    Candidate Selection
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-[#0B1118] text-[#E9A76A] border border-[#202F3C]">
                    Demonstration data
                  </span>
                </div>
                <button
                  onClick={() => setIsCandidateDrawerOpen(false)}
                  className="p-1 rounded-lg text-[#90A4AF] hover:text-[#E9F0F3] hover:bg-[#202F3C] transition cursor-pointer"
                >
                  <ChevronDown className="w-4 h-4" />
                </button>
              </div>

              {/* Molecule Switcher */}
              <div className="flex items-center gap-1.5">
                {displayedCandidates.map((cand) => {
                  const isSelected = activeCandidate?.id === cand.id;
                  return (
                    <button
                      key={cand.id}
                      onClick={() => {
                        if (onSelectCandidate) onSelectCandidate(cand.id);
                        if (cand.id === 'bibr1532') handleFocusOnInhibitor();
                      }}
                      className={`flex-1 py-1 px-2 rounded-lg text-xs font-mono transition cursor-pointer ${
                        isSelected
                          ? 'bg-[#59C9C0] text-[#0B1118] font-bold shadow-sm'
                          : 'bg-[#0B1118] text-[#90A4AF] hover:text-[#E9F0F3] border border-[#202F3C]'
                      }`}
                    >
                      {cand.name}
                    </button>
                  );
                })}
              </div>

              {/* Illustrative Docking Score Callout */}
              <div className="p-2 rounded-xl bg-[#0B1118] border border-[#202F3C] flex items-center justify-between">
                <div>
                  <span className="text-[10px] text-[#90A4AF] block">
                    Illustrative Mock Docking Score:
                  </span>
                  <span className="text-[10px] text-[#627783]">
                    Workflow demonstration value; not actual docking results.
                  </span>
                </div>
                <span className="text-base font-bold font-mono text-[#E9A76A]">
                  {illustrativeScore} kcal/mol
                </span>
              </div>

              {/* Brief Interaction Hypothesis */}
              <div className="text-[11px] text-[#90A4AF] leading-relaxed">
                <strong className="text-[#E9F0F3]">Hypothesis: </strong>
                {activeCandidate?.id === 'bibr1532'
                  ? 'BIBR1532 engages TERT Phe870, Leu977, and Met980 in the 3.0 Å cryo-EM pocket.'
                  : `Evaluating potential shape complementarity against the TERT allosteric cavity (predicted pIC50: ${activeCandidate?.prediction?.predicted_pic50?.toFixed(2) || 'pending'}).`}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
