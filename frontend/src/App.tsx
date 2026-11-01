/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import { NavigationSidebar, NavigationTab } from './components/NavigationSidebar';
import { PipelineView } from './components/PipelineView';
import { MolecularViewer } from './components/MolecularViewer';
import { MolecularInspector } from './components/MolecularInspector';
import { AgentRunsView } from './components/AgentRunsView';
import { LiteratureView } from './components/LiteratureView';
import {
  dockingService,
  TARGET_TELOMERASE_9Q14,
  SHORTLISTED_CANDIDATES,
  INITIAL_DOCKING_RESULTS,
  INITIAL_RESEARCH_NOTES
} from './services/dockingService';
import {
  Protein,
  Ligand,
  DockingResult,
  ResearchNote,
  ComponentVisibility,
  SelectedComponentType
} from './types/docking';
import { X, BookOpen } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<NavigationTab>('pipeline');
  const [protein, setProtein] = useState<Protein>(TARGET_TELOMERASE_9Q14);
  const [candidates, setCandidates] = useState<Ligand[]>(SHORTLISTED_CANDIDATES);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>('bibr1532');
  const [dockingResults, setDockingResults] = useState<Record<string, DockingResult>>(INITIAL_DOCKING_RESULTS);
  const [notes, setNotes] = useState<ResearchNote[]>(INITIAL_RESEARCH_NOTES);
  const [isLoadingScreening, setIsLoadingScreening] = useState<boolean>(false);
  const [screeningSource, setScreeningSource] = useState<'backend' | 'demo'>('backend');

  // 3D Viewport Controls & Selections
  const [selectedComponent, setSelectedComponent] = useState<SelectedComponentType>('all');
  const [visibility, setVisibility] = useState<ComponentVisibility>({
    showProtein: true,
    showRna: true,
    showDna: true,
    showInhibitor: true
  });
  const [focusedResidue, setFocusedResidue] = useState<{ resi: number; chain: string } | null>(null);

  // Initialize data from centralized service
  useEffect(() => {
    const initData = async () => {
      const tgt = await dockingService.getTargetProtein();
      const cands = await dockingService.getCandidates();
      const docks = await dockingService.getAllDockingResults();
      const initialNotes = dockingService.getNotes();

      setProtein(tgt);
      setCandidates(cands);
      setDockingResults(docks);
      setNotes(initialNotes);
    };

    initData();

    const unsubscribe = dockingService.subscribe(() => {
      setNotes(dockingService.getNotes());
    });

    return () => unsubscribe();
  }, []);

  // Global keyboard shortcuts for navigation and Research Notes overlay
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Avoid capturing single-key numbers when typing inside interactive elements
      const activeElem = document.activeElement;
      const isInputActive =
        activeElem &&
        (activeElem.tagName === 'INPUT' ||
          activeElem.tagName === 'TEXTAREA' ||
          activeElem.tagName === 'SELECT' ||
          (activeElem as HTMLElement).isContentEditable);

      if (isInputActive) {
        return;
      }

      // 3. Tab navigation shortcuts 1-5 without modifiers
      if (!e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey) {
        switch (e.key) {
          case '1':
            e.preventDefault();
            setActiveTab('pipeline');
            setFocusedResidue(null);
            break;
          case '2':
            e.preventDefault();
            setActiveTab('playground');
            break;
          case '3':
            e.preventDefault();
            setActiveTab('literature');
            setFocusedResidue(null);
            break;
          case '4':
            e.preventDefault();
            setActiveTab('agents');
            setFocusedResidue(null);
            break;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleToggleVisibility = (key: keyof ComponentVisibility) => {
    setVisibility((prev) => ({
      ...prev,
      [key]: !prev[key]
    }));
  };

  const handleFocusInhibitor = () => {
    setSelectedComponent('inhibitor');
    if (!visibility.showInhibitor) {
      setVisibility((prev) => ({ ...prev, showInhibitor: true }));
    }
  };

  const handleRunScreening = async (count: number) => {
    setIsLoadingScreening(true);
    try {
      const res = await dockingService.fetchScreeningShortlist(count);
      setCandidates(res.entries);
      setScreeningSource(res.source);
      if (res.entries.length > 0) {
        setSelectedCandidateId(res.entries[0].id);
      }
    } finally {
      setIsLoadingScreening(false);
    }
  };

  const handleExploreInPlayground = (candidateId: string) => {
    setSelectedCandidateId(candidateId);
    setActiveTab('playground');
    // If exploring BIBR1532, focus inhibitor
    if (candidateId === 'bibr1532') {
      handleFocusInhibitor();
    }
  };

  const handleAddNote = (
    category: 'Observation' | 'Question' | 'Hypothesis' | 'Next Experiment',
    content: string,
    title?: string
  ) => {
    const newNote = dockingService.addNote({
      title: title || `Observation: ${protein.name}`,
      category,
      content,
      targetId: protein.id,
      candidateId: selectedCandidateId,
      tags: [protein.pdbId, 'Telomerase', 'BIBR1532']
    });
    setNotes(dockingService.getNotes());
    return newNote;
  };

  const handleAddNoteForCandidate = (candidateId: string) => {
    const candidate = candidates.find((c) => c.id === candidateId);
    if (!candidate) return;
    handleAddNote(
      'Observation',
      `Inspected candidate ${candidate.name} targeting ${candidate.targetSite}. QSAR predicted pIC50: ${candidate.prediction?.predicted_pic50.toFixed(2) || '—'}. Awaiting 3D docking pipeline execution.`,
      `Pipeline Record: ${candidate.name}`
    );
  };

  const handleUpdateNote = (id: string, updates: Partial<Omit<ResearchNote, 'id'>>) => {
    dockingService.updateNote(id, updates);
    setNotes(dockingService.getNotes());
  };

  const handleDeleteNote = (id: string) => {
    dockingService.deleteNote(id);
    setNotes(dockingService.getNotes());
  };

  return (
    <div className="flex h-screen w-screen bg-[#0B1118] text-[#E9F0F3] overflow-hidden font-sans select-none">
      {/* 1. Left Sidebar: 5-Stage Navigation Workflow */}
      <NavigationSidebar
        activeTab={activeTab}
        onSelectTab={(tab) => {
          setActiveTab(tab);
          setFocusedResidue(null);
        }}
      />

      {/* 2. Main Center Workspace */}
      <main className="flex-1 flex overflow-hidden relative">
        {/* 1. PIPELINE */}
        {activeTab === 'pipeline' && (
          <div className="flex-1 h-full min-h-0">
            <PipelineView />
          </div>
        )}

        {/* 3. MOLECULAR PLAYGROUND TAB (Visual Centerpiece) */}
        {activeTab === 'playground' && (
          <div className="flex-1 flex h-full overflow-hidden">
            <div className="flex-1 h-full">
              <MolecularViewer
                protein={protein}
                selectedComponent={selectedComponent}
                onSelectComponent={setSelectedComponent}
                visibility={visibility}
                onToggleVisibility={handleToggleVisibility}
                focusedResidue={focusedResidue}
                candidates={candidates}
                selectedCandidateId={selectedCandidateId}
                onSelectCandidate={(id) => {
                  setSelectedCandidateId(id);
                  if (id === 'bibr1532') {
                    handleFocusInhibitor();
                  }
                }}
                dockingResults={dockingResults}
                onAddNote={handleAddNote}
                onNavigateToTab={(tab) => setActiveTab(tab as any)}
              />
            </div>

            {/* Right Sidebar: Molecular Inspector */}
            <MolecularInspector
              protein={protein}
              selectedComponent={selectedComponent}
              onSelectComponent={setSelectedComponent}
              visibility={visibility}
              onToggleVisibility={handleToggleVisibility}
              onFocusInhibitor={handleFocusInhibitor}
              candidates={candidates}
              selectedCandidateId={selectedCandidateId}
              onSelectCandidate={setSelectedCandidateId}
              dockingResults={dockingResults}
              onAddNoteForCandidate={handleAddNoteForCandidate}
            />
          </div>
        )}

        {/* 5. LITERATURE TAB */}
        {activeTab === 'agents' && <AgentRunsView candidate={candidates.find(c => c.id === selectedCandidateId)} />}

        {activeTab === 'literature' && (
          <div className="flex-1 h-full">
            <LiteratureView />
          </div>
        )}
      </main>

      {/* Accessible Slide-over / Modal for Research Notes */}
    </div>
  );
}
