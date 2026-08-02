// Mock Data matching the screenshot
const mockData = {
    "dev_001": [
        { id: 0, conf: 0.912, px: 14886.87, py: 7732.57, lat: 11.475070, lng: 77.889690 },
        { id: 1, conf: 0.745, px: 15200.12, py: 7900.45, lat: 11.474000, lng: 77.888000 },
        { id: 2, conf: 0.381, px: 14500.33, py: 7600.11, lat: 11.476000, lng: 77.891000 }
    ],
    "dev_002": [
        { id: 3, conf: 0.850, px: 5000, py: 5000, lat: 11.48, lng: 77.89 },
        { id: 4, conf: 0.420, px: 5100, py: 5100, lat: 11.481, lng: 77.891 }
    ],
    "dev_003": [
        { id: 5, conf: 0.950, px: 1000, py: 1000, lat: 11.47, lng: 77.88 },
        { id: 6, conf: 0.920, px: 1200, py: 1200, lat: 11.471, lng: 77.881 }
    ]
};

// State
let currentScene = "dev_001";
let map;
let markersLayer;
let activeMarker = null;

// Initialize Map
function initMap() {
    // Esri World Imagery (Satellite)
    map = L.map('map', { zoomControl: false }).setView([11.475070, 77.889690], 15);
    
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
        maxZoom: 19
    }).addTo(map);

    markersLayer = L.layerGroup().addTo(map);
}

function getConfColor(conf) {
    if (conf >= 0.75) return '#22c55e'; // green
    if (conf >= 0.50) return '#eab308'; // yellow
    return '#ef4444'; // red
}

function getConfClass(conf) {
    if (conf >= 0.75) return 'high';
    if (conf >= 0.50) return 'mid';
    return 'low';
}

function renderScenes() {
    const list = document.getElementById('scene-list');
    list.innerHTML = '';
    
    document.getElementById('scene-count').textContent = Object.keys(mockData).length;

    for (const [sceneId, detections] of Object.entries(mockData)) {
        const li = document.createElement('li');
        li.className = `scene-item ${sceneId === currentScene ? 'active' : ''}`;
        li.innerHTML = `
            <span>${sceneId}</span>
            <span style="font-weight: 600;">${detections.length}</span>
        `;
        li.onclick = () => selectScene(sceneId);
        list.appendChild(li);
    }
}

function selectScene(sceneId) {
    currentScene = sceneId;
    renderScenes();
    loadSceneData();
}

function loadSceneData() {
    const detections = mockData[currentScene] || [];
    
    // Sort by confidence descending
    detections.sort((a, b) => b.conf - a.conf);

    // Update Stats
    document.getElementById('stat-total').textContent = detections.length;
    document.getElementById('map-signal-count').textContent = `${detections.length} SIGNALS`;
    
    if (detections.length > 0) {
        const mean = detections.reduce((sum, d) => sum + d.conf, 0) / detections.length;
        document.getElementById('stat-mean').textContent = mean.toFixed(3);
        document.getElementById('stat-high').textContent = detections[0].conf.toFixed(3);
        document.getElementById('stat-low').textContent = detections[detections.length - 1].conf.toFixed(3);
    } else {
        document.getElementById('stat-mean').textContent = '0.000';
        document.getElementById('stat-high').textContent = '-';
        document.getElementById('stat-low').textContent = '-';
    }

    // Render Log
    const logList = document.getElementById('detection-list');
    logList.innerHTML = '';

    markersLayer.clearLayers();
    const bounds = [];

    detections.forEach(d => {
        // Log Item
        const li = document.createElement('li');
        li.className = 'detection-item';
        li.id = `log-${d.id}`;
        li.innerHTML = `
            <span class="conf-pill ${getConfClass(d.conf)}">${d.conf.toFixed(2)}</span>
            <span>x:${Math.round(d.px)} | y:${Math.round(d.py)}</span>
        `;
        li.onclick = () => selectDetection(d);
        logList.appendChild(li);

        // Map Marker
        const color = getConfColor(d.conf);
        const markerHtml = `
            <div style="
                width: 12px; height: 12px; 
                background: ${color}; 
                border: 2px solid white; 
                border-radius: 50%; 
                box-shadow: 0 0 8px ${color};">
            </div>
        `;
        
        const icon = L.divIcon({
            html: markerHtml,
            className: 'custom-marker',
            iconSize: [12, 12],
            iconAnchor: [6, 6]
        });

        const marker = L.marker([d.lat, d.lng], { icon }).addTo(markersLayer);
        marker.on('click', () => selectDetection(d));
        d.marker = marker; // save ref

        bounds.push([d.lat, d.lng]);
    });

    if (bounds.length > 0) {
        map.fitBounds(bounds, { padding: [50, 50], maxZoom: 17 });
    }
    
    // Select first by default
    if (detections.length > 0) {
        selectDetection(detections[0]);
    }
}

function selectDetection(d) {
    // Update active state in log
    document.querySelectorAll('.detection-item').forEach(el => el.classList.remove('active'));
    const logItem = document.getElementById(`log-${d.id}`);
    if (logItem) {
        logItem.classList.add('active');
        logItem.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    // Update Inspector
    document.getElementById('insp-conf').textContent = d.conf.toFixed(4);
    
    const confBadge = document.getElementById('insp-conf');
    const color = getConfColor(d.conf);
    confBadge.style.color = color;
    confBadge.style.borderColor = color;
    
    // Convert hex to rgb for rgba background
    const hex = color.replace('#', '');
    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);
    confBadge.style.background = `rgba(${r}, ${g}, ${b}, 0.1)`;

    document.getElementById('insp-id').textContent = d.id;
    document.getElementById('insp-px').textContent = d.px.toFixed(2);
    document.getElementById('insp-py').textContent = d.py.toFixed(2);
    document.getElementById('insp-lat').textContent = d.lat.toFixed(6);
    document.getElementById('insp-lng').textContent = d.lng.toFixed(6);

    // Pan map smoothly
    map.flyTo([d.lat, d.lng], 18, { duration: 1.5 });
    
    // Animate marker popup effect
    if (activeMarker) {
        activeMarker.getElement().style.transform = 'scale(1)';
    }
    d.marker.getElement().style.transform = 'scale(1.5)';
    d.marker.getElement().style.transition = 'transform 0.3s ease';
    activeMarker = d.marker;
}

// Bootstrap
document.addEventListener('DOMContentLoaded', () => {
    initMap();
    renderScenes();
    loadSceneData();
});
