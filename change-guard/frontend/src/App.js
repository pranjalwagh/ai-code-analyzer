import { useState, useEffect } from 'react';
import { db } from './firebase';
import { doc, getDoc, onSnapshot, collection, getDocs } from "firebase/firestore";
import DependencyGraph from './components/DependencyGraph';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { materialDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

function App() {
  const [commitSha, setCommitSha] = useState('265d619dbb776c4da1033e71a1467fa6673ac99d'); // Default for demonstration
  const [analysisResult, setAnalysisResult] = useState(null);
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // --- NEW: Function to process raw Firestore data into D3 format ---
  const processGraphData = (analysis, graphDocs) => {
    if (!analysis || !graphDocs) return { nodes: [], links: [] };

    const changedFiles = analysis.atomic_changes?.map(c => c.file) || [];
    const impactedClasses = analysis.impacted_components?.direct || [];
    
    const nodes = graphDocs.map(doc => {
      const docData = doc.data();
      const id = doc.id;
      let status = 'normal';
      if (changedFiles.includes(docData.file_path)) {
        status = 'changed';
      } else if (impactedClasses.includes(id)) {
        status = 'impacted';
      }
      return { id, status, ...docData };
    });

    const links = [];
    nodes.forEach(node => {
      node.imports?.forEach(imp => {
        // Only create links for nodes that exist in our graph
        if (nodes.some(n => n.id === imp)) {
          links.push({ source: node.id, target: imp });
        }
      });
    });

    return { nodes, links };
  };

  useEffect(() => {
    const fetchAnalysis = async () => {
      if (!commitSha) {
        setAnalysisResult(null);
        setGraphData({ nodes: [], links: [] });
        return;
      };

      setLoading(true);
      setError('');
      setAnalysisResult(null);
      setGraphData({ nodes: [], links: [] });

      // Listen for real-time updates on the analysis result
      const unsub = onSnapshot(doc(db, "analysis_results", commitSha), async (doc) => {
        if (doc.exists()) {
          const analysisData = doc.data();
          setAnalysisResult(analysisData);

          if (analysisData.status === 'Completed' || analysisData.status === 'Processing') {
            // --- NEW: Fetch the graph data once analysis is available ---
            try {
              const graphCollectionRef = collection(db, "graph_snapshots", commitSha, "graph");
              const graphSnapshot = await getDocs(graphCollectionRef);
              if (!graphSnapshot.empty) {
                const processedData = processGraphData(analysisData, graphSnapshot.docs);
                setGraphData(processedData);
              }
            } catch (graphError) {
              console.error("Error fetching graph data:", graphError);
              setError("Could not load dependency graph.");
            }
          }

          if(analysisData.status === 'Failed') {
            setError(`Analysis failed: ${analysisData.error || 'Unknown error.'}`);
          }

        } else {
          setAnalysisResult(null); // Or some 'not found' state
          setError(`No analysis found for commit SHA: ${commitSha}`);
        }
        setLoading(false);
      });

      // Cleanup subscription on unmount
      return () => unsub();
    }
    
    fetchAnalysis();
  }, [commitSha]); // Rerun when commitSha changes

  // --- NEW: Function to handle commit SHA changes from input ---
  const handleCommitChange = (e) => {
    // Basic debounce to prevent firing on every keystroke
    const timer = setTimeout(() => {
      setCommitSha(e.target.value);
    }, 1000);
    return () => clearTimeout(timer);
  }

  return (
    <div className="bg-slate-50 min-h-screen font-sans">
      <header className="bg-white shadow-sm">
        <div className="container mx-auto px-8 py-4">
          <h1 className="text-2xl font-bold text-slate-800">ChangeGuard :: Impact Analysis Report</h1>
        </div>
      </header>

      <main className="container mx-auto p-8">
        <div className="mb-8">
          <label htmlFor="commit-sha" className="block text-sm font-medium text-slate-700 mb-1">
            Displaying analysis for Commit SHA:
          </label>
          <input
            id="commit-sha"
            type="text"
            defaultValue={commitSha}
            onChange={handleCommitChange}
            className="w-full md:w-1/2 p-2 border border-slate-300 rounded-md shadow-sm font-mono text-sm"
            placeholder="Enter commit SHA to analyze..."
          />
        </div>
        
        {loading && (
          <div className="text-center p-12"><p className="text-slate-500 text-lg">Loading Analysis Report...</p></div>
        )}

        {error && !loading && (
           <div className="text-center p-12 bg-red-50 rounded-lg shadow"><p className="text-red-700 font-semibold">{error}</p></div>
        )}
        
        {!loading && !error && analysisResult && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Left Column: Graph & Summary */}
            <div className="lg:col-span-2 space-y-8">
              <div className="bg-white p-6 rounded-lg shadow">
                 <h2 className="text-xl font-semibold text-slate-900 mb-4">Dependency Graph</h2>
                 {graphData.nodes.length > 0 ? (
                    <DependencyGraph nodes={graphData.nodes} links={graphData.links} />
                 ) : (
                    <p className="text-slate-500">{(analysisResult?.status === 'Processing') ? 'Generating graph...' : 'No graph data available.'}</p>
                 )}
              </div>

               <div className="bg-white p-6 rounded-lg shadow">
                <h2 className="text-xl font-semibold text-slate-900 mb-3">AI-Generated Summary</h2>
                <div className="prose prose-slate max-w-none text-slate-600">
                  <p className="whitespace-pre-wrap font-sans">{analysisResult.ai_summary || 'Summary not available.'}</p>
                </div>
              </div>
            </div>

            {/* Right Column: Tests & Details */}
            <div className="space-y-8">
               <div className="bg-white p-6 rounded-lg shadow">
                 <h2 className="text-xl font-semibold text-slate-900 mb-3">AI-Suggested Tests</h2>
                 <SyntaxHighlighter language="java" style={materialDark} customStyle={{ borderRadius: '0.375rem' }} wrapLongLines={true}>
                    {analysisResult.ai_suggested_test || 'No tests suggested.'}
                 </SyntaxHighlighter>
               </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;