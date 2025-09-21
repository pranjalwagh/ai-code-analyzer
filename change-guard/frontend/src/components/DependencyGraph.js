import React, { useEffect, useState, useRef } from 'react';
import * as d3 from 'd3';


const DependencyGraph = ({ nodes, links }) => {
    const svgRef = useRef();
    const containerRef = useRef(); // <-- ADD THIS
    const [isFullscreen, setIsFullscreen] = useState(false); // <-- ADD THIS

    useEffect(() => {
        if (!nodes || !links || nodes.length === 0) return;

        const width = 800;
        const height = 600;

        const svg = d3.select(svgRef.current)
            .attr('width', width)
            .attr('height', height)
            .attr('viewBox', [0, 0, width, height])
            .attr('style', 'max-width: 100%; height: auto; border: 1px solid #e2e8f0; border-radius: 8px; cursor: grab;');

        svg.selectAll('*').remove();

        // --- START: Changes for Pan and Zoom ---

        // 1. Create a container <g> that will hold all the nodes and links.
        // We will apply zoom transformations to this group.
        const container = svg.append('g');

        // 2. Define the zoom behavior
        const zoomBehavior = d3.zoom()
            .scaleExtent([0.2, 5])
            .filter(event => event.type === 'wheel' ? event.altKey : true) // Only zoom on wheel when Alt key is pressed
            .on('zoom', (event) => {
                container.attr('transform', event.transform);
            });

        svg.append('text')
            .attr('x', 10)
            .attr('y', 20)
            .attr('font-size', '10px')
            .attr('fill', '#94a3b8')
            .text('Hold [Alt] + Scroll to zoom');

        // 3. Apply the zoom behavior to the main SVG element.
        svg.call(zoomBehavior);

        // --- END: Changes for Pan and Zoom ---


        const color = (node) => {
            switch (node.status) {
                case 'changed': return '#ef4444'; // Red-500
                case 'impacted': return '#f59e0b'; // Amber-500
                default: return '#64748b'; // Slate-500
            }
        };

        const simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(d => d.id).distance(90))
            .force('charge', d3.forceManyBody().strength(-150))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collide', d3.forceCollide().radius(d => d.radius * 1.2));

        // Append links and nodes to the container, not the svg itself.
        const link = container.append('g')
            .attr('stroke', '#94a3b8')
            .attr('stroke-opacity', 0.6)
            .selectAll('line')
            .data(links)
            .join('line')
            .attr('stroke-width', 1.5);

        const node = container.append('g')
            .selectAll('g')
            .data(nodes)
            .join('g')
            .call(drag(simulation));

        node.append('circle')
            .attr('r', 8)
            .attr('fill', color)
            .attr('stroke', '#f8fafc')
            .attr('stroke-width', 1.5);

        node.append('text')
            .attr('x', 12)
            .attr('y', '0.31em')
            .text(d => d.id.split('.').pop())
            .attr('font-size', '10px')
            .attr('fill', '#334155');

        node.append('title')
            .text(d => `${d.id}\nStatus: ${d.status}`);

        simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);

            node.attr('transform', d => `translate(${d.x},${d.y})`);
        });

    }, [nodes, links]);

    useEffect(() => {
        const handleFullscreenChange = () => {
            setIsFullscreen(!!document.fullscreenElement);
        };
        document.addEventListener('fullscreenchange', handleFullscreenChange);
        return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
    }, []);

    const drag = (simulation) => {
        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }
        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }
        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }
        return d3.drag()
            .on('start', dragstarted)
            .on('drag', dragged)
            .on('end', dragended);
    };

    const toggleFullscreen = () => {
        if (!document.fullscreenElement) {
            containerRef.current.requestFullscreen();
        } else {
            document.exitFullscreen();
        }
    };

    // REPLACE your current `return (...)` with this
    return (
        <div
            ref={containerRef}
            className={`relative ${isFullscreen ? 'fixed inset-0 bg-slate-50 z-50 p-4 flex justify-center items-center' : ''}`}
        >
            <button
                onClick={toggleFullscreen}
                className="absolute top-2 right-2 p-1.5 bg-white/70 hover:bg-white rounded-md text-slate-600 z-10 border border-slate-200"
                title={isFullscreen ? 'Exit Fullscreen' : 'Enter Fullscreen'}
            >
                {/* SVG icon for fullscreen */}
                <svg width="16" height="16" fill="currentColor" viewBox="0 0 16 16">
                    {isFullscreen ?
                        <path d="M5.5 0a.5.5 0 0 1 .5.5v4A.5.5 0 0 1 5 5h-4a.5.5 0 0 1 0-1h3.5V.5a.5.5 0 0 1 .5-.5zm5 0a.5.5 0 0 1 .5.5v3.5h3.5a.5.5 0 0 1 0 1h-4a.5.5 0 0 1-.5-.5v-4a.5.5 0 0 1 .5-.5zM5 10.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 0 1H5.5V15a.5.5 0 0 1-1 0v-4a.5.5 0 0 1 .5-.5zM.5 11a.5.5 0 0 1 .5-.5h3.5v3.5a.5.5 0 0 1-1 0V11H1a.5.5 0 0 1-.5-.5z" /> :
                        <path d="M1.5 1a.5.5 0 0 0-.5.5v4a.5.5 0 0 1-1 0v-4A1.5 1.5 0 0 1 1.5 0h4a.5.5 0 0 1 0 1h-4zM10 .5a.5.5 0 0 1 .5-.5h4A1.5 1.5 0 0 1 16 1.5v4a.5.5 0 0 1-1 0v-3.5h-3.5a.5.5 0 0 1-.5-.5zM.5 10a.5.5 0 0 1 .5.5v3.5h3.5a.5.5 0 0 1 0 1h-4A1.5 1.5 0 0 1 0 14.5v-4a.5.5 0 0 1 .5-.5zm15 0a.5.5 0 0 1 .5.5v4a1.5 1.5 0 0 1-1.5 1.5h-4a.5.5 0 0 1 0-1h3.5v-3.5a.5.5 0 0 1 .5-.5z" />
                    }
                </svg>
            </button>
            <svg ref={svgRef}></svg>
        </div>
    );
};

export default DependencyGraph;