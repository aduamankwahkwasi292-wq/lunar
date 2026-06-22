// LUNAR - Epic Live Nebula Background - Ultimate Smooth Edition
class NebulaBackground {
    constructor() {
        this.canvas = document.getElementById('nebula-canvas');
        
        // Enable smooth rendering with high DPI support
        this.dpr = Math.min(window.devicePixelRatio || 1, 2);
        this.ctx = this.canvas.getContext('2d', {
            alpha: false,
            desynchronized: true
        });
        
        // Enable image smoothing for anti-aliasing
        this.ctx.imageSmoothingEnabled = true;
        this.ctx.imageSmoothingQuality = 'high';
        
        this.particles = [];
        this.stars = [];
        this.shootingStars = [];
        this.nebulaClouds = [];
        this.energyWaves = [];
        this.cosmicStrands = [];
        this.orbs = [];
        this.warpStars = [];
        this.time = 0;
        this.mouseX = 0.5;
        this.mouseY = 0.5;
        this.targetMouseX = 0.5;
        this.targetMouseY = 0.5;
        
        // Warp drive state
        this.isWarping = false;
        this.warpProgress = 0;
        this.warpDuration = 120; // frames (~2 seconds at 60fps)
        this.warpPhase = 'idle'; // 'idle', 'accelerating', 'warping', 'decelerating'
        
        this.resize();
        this.init();
        this.bindEvents();
        this.animate();
    }

    resize() {
        // High DPI canvas for crisp, smooth rendering
        const rect = this.canvas.getBoundingClientRect();
        this.width = rect.width || window.innerWidth;
        this.height = rect.height || window.innerHeight;
        
        this.canvas.width = this.width * this.dpr;
        this.canvas.height = this.height * this.dpr;
        this.canvas.style.width = this.width + 'px';
        this.canvas.style.height = this.height + 'px';
        
        // Scale context for high DPI
        this.ctx.scale(this.dpr, this.dpr);
        
        // Re-enable smoothing after resize
        this.ctx.imageSmoothingEnabled = true;
        this.ctx.imageSmoothingQuality = 'high';
        
        this.centerX = this.width / 2;
        this.centerY = this.height / 2;
        
        // Reinitialize on resize
        if (this.stars.length > 0) {
            this.stars = [];
            this.particles = [];
            this.nebulaClouds = [];
            this.cosmicStrands = [];
            this.orbs = [];
            this.init();
        }
    }

    bindEvents() {
        window.addEventListener('resize', () => this.resize());
        document.addEventListener('mousemove', (e) => {
            this.targetMouseX = e.clientX / this.width;
            this.targetMouseY = e.clientY / this.height;
        });
    }

    init() {
        // Create LOTS of stars - multiple layers for incredible depth
        for (let i = 0; i < 200; i++) {
            const layer = Math.floor(Math.random() * 4);
            this.stars.push({
                x: Math.random() * this.width,
                y: Math.random() * this.height,
                size: Math.random() * (3 - layer * 0.5) + 0.3,
                brightness: Math.random() * 0.8 + 0.2,
                twinkleSpeed: Math.random() * 0.03 + 0.005,
                twinkleOffset: Math.random() * Math.PI * 2,
                layer: layer,
                color: this.getStarColor()
            });
        }

        // Create floating particles (cosmic dust) - more of them!
        for (let i = 0; i < 60; i++) {
            this.particles.push({
                x: Math.random() * this.width,
                y: Math.random() * this.height,
                size: Math.random() * 4 + 1,
                speedX: (Math.random() - 0.5) * 0.5,
                speedY: (Math.random() - 0.5) * 0.5,
                opacity: Math.random() * 0.6 + 0.1,
                hue: Math.random() * 100 + 200,  // Blue to purple range
                pulse: Math.random() * Math.PI * 2,
                rotationSpeed: (Math.random() - 0.5) * 0.02
            });
        }

        // Create MASSIVE nebula cloud centers - COOL DARK TONES WITH PURPLE
        const nebulaColors = [
            { hue: 275, sat: 85 },  // Dark purple
            { hue: 260, sat: 90 },  // Deep violet
            { hue: 220, sat: 90 },  // Deep ocean blue
            { hue: 285, sat: 80 },  // Dark magenta-purple
            { hue: 200, sat: 95 },  // Electric cyan
            { hue: 270, sat: 88 },  // Royal purple
            { hue: 230, sat: 90 },  // Sapphire blue
            { hue: 290, sat: 75 },  // Deep plum
            { hue: 250, sat: 85 },  // Indigo purple
            { hue: 195, sat: 88 },  // Ice blue
        ];
        
        for (let i = 0; i < 6; i++) {
            const colorPreset = nebulaColors[i % nebulaColors.length];
            this.nebulaClouds.push({
                x: Math.random() * this.width,
                y: Math.random() * this.height,
                radius: Math.random() * 500 + 300,
                hue: colorPreset.hue + (Math.random() - 0.5) * 30,
                saturation: colorPreset.sat,
                drift: {
                    x: (Math.random() - 0.5) * 0.4,
                    y: (Math.random() - 0.5) * 0.4,
                    angle: Math.random() * Math.PI * 2,
                    angleSpeed: (Math.random() - 0.5) * 0.001
                },
                pulseSpeed: Math.random() * 0.008 + 0.003,
                pulseOffset: Math.random() * Math.PI * 2,
                intensity: Math.random() * 0.5 + 0.5
            });
        }

        // Create cosmic strands (energy filaments)
        for (let i = 0; i < 4; i++) {
            this.cosmicStrands.push({
                startX: Math.random() * this.width,
                startY: Math.random() * this.height,
                length: Math.random() * 400 + 200,
                angle: Math.random() * Math.PI * 2,
                wave: Math.random() * Math.PI * 2,
                hue: Math.random() * 80 + 210,  // Blue to purple tones
                speed: Math.random() * 0.02 + 0.01
            });
        }

        // Create smooth glowing orbs (lunar orbs)
        for (let i = 0; i < 3; i++) {
            this.orbs.push({
                x: Math.random() * this.width,
                y: Math.random() * this.height,
                radius: Math.random() * 50 + 30,
                hue: Math.random() * 80 + 220,  // Blue to purple orbs
                speed: Math.random() * 0.3 + 0.1,
                angle: Math.random() * Math.PI * 2,
                orbitRadius: Math.random() * 200 + 100,
                orbitSpeed: (Math.random() - 0.5) * 0.002,
                pulse: Math.random() * Math.PI * 2
            });
        }
    }

    drawOrbs() {
        this.orbs.forEach(orb => {
            // Smooth orbital movement
            orb.angle += orb.orbitSpeed;
            orb.pulse += 0.02;
            
            const wobbleX = Math.sin(orb.angle) * orb.orbitRadius * 0.3;
            const wobbleY = Math.cos(orb.angle * 0.7) * orb.orbitRadius * 0.3;
            
            const x = orb.x + wobbleX + (this.mouseX - 0.5) * 50;
            const y = orb.y + wobbleY + (this.mouseY - 0.5) * 50;
            
            // Smooth pulsing
            const pulseFactor = 1 + Math.sin(orb.pulse) * 0.15;
            const radius = orb.radius * pulseFactor;
            
            // Multi-layer glow for ultra-smooth appearance
            for (let layer = 2; layer >= 0; layer--) {
                const layerRadius = radius * (1 + layer * 0.6);
                const opacity = 0.012 / (layer + 1);
                
                const gradient = this.ctx.createRadialGradient(x, y, 0, x, y, layerRadius);
                gradient.addColorStop(0, `hsla(${orb.hue}, 90%, 55%, ${opacity * 1.5})`);
                gradient.addColorStop(0.3, `hsla(${orb.hue + 15}, 80%, 40%, ${opacity * 0.7})`);
                gradient.addColorStop(0.6, `hsla(${orb.hue + 30}, 70%, 28%, ${opacity * 0.3})`);
                gradient.addColorStop(1, 'transparent');
                
                this.ctx.beginPath();
                this.ctx.fillStyle = gradient;
                this.ctx.arc(x, y, layerRadius, 0, Math.PI * 2);
                this.ctx.fill();
            }
        });
    }

    getStarColor() {
        const colors = [
            'rgba(255, 255, 255, 1)',      // White
            'rgba(200, 220, 255, 1)',      // Blue-white
            'rgba(255, 240, 220, 1)',      // Warm white
            'rgba(180, 200, 255, 1)',      // Cool blue
            'rgba(255, 200, 200, 1)',      // Reddish
            'rgba(200, 255, 255, 1)',      // Cyan tint
        ];
        return colors[Math.floor(Math.random() * colors.length)];
    }

    spawnShootingStar() {
        // More frequent and spectacular shooting stars
        if (Math.random() < 0.015) {
            const startX = Math.random() * this.width;
            const startY = Math.random() * this.height * 0.6;
            const isMeteor = Math.random() < 0.3; // 30% chance of big meteor
            
            this.shootingStars.push({
                x: startX,
                y: startY,
                length: isMeteor ? Math.random() * 200 + 150 : Math.random() * 120 + 60,
                speed: isMeteor ? Math.random() * 25 + 18 : Math.random() * 18 + 8,
                angle: Math.PI / 4 + (Math.random() - 0.5) * 0.5,
                opacity: 1,
                thickness: isMeteor ? Math.random() * 4 + 2 : Math.random() * 2 + 1,
                hue: Math.random() * 60 + 200, // Blue to purple
                isMeteor: isMeteor,
                sparkles: []
            });
        }
    }

    updateShootingStars() {
        for (let i = this.shootingStars.length - 1; i >= 0; i--) {
            const star = this.shootingStars[i];
            star.x += Math.cos(star.angle) * star.speed;
            star.y += Math.sin(star.angle) * star.speed;
            star.opacity -= star.isMeteor ? 0.008 : 0.018;
            
            // Spawn sparkles for meteors
            if (star.isMeteor && Math.random() < 0.4) {
                star.sparkles.push({
                    x: star.x + (Math.random() - 0.5) * 10,
                    y: star.y + (Math.random() - 0.5) * 10,
                    size: Math.random() * 3 + 1,
                    opacity: 1,
                    vx: (Math.random() - 0.5) * 3,
                    vy: (Math.random() - 0.5) * 3
                });
            }
            
            // Update sparkles
            for (let j = star.sparkles.length - 1; j >= 0; j--) {
                const sparkle = star.sparkles[j];
                sparkle.x += sparkle.vx;
                sparkle.y += sparkle.vy;
                sparkle.opacity -= 0.05;
                sparkle.size *= 0.95;
                if (sparkle.opacity <= 0) star.sparkles.splice(j, 1);
            }
            
            if (star.opacity <= 0 || star.x > this.width + 100 || star.y > this.height + 100) {
                this.shootingStars.splice(i, 1);
            }
        }
    }

    drawShootingStars() {
        this.shootingStars.forEach(star => {
            // Draw sparkles first (behind the meteor)
            star.sparkles.forEach(sparkle => {
                this.ctx.beginPath();
                this.ctx.fillStyle = `rgba(255, 220, 180, ${sparkle.opacity})`;
                this.ctx.arc(sparkle.x, sparkle.y, sparkle.size, 0, Math.PI * 2);
                this.ctx.fill();
            });
            
            // Main trail gradient
            const gradient = this.ctx.createLinearGradient(
                star.x, star.y,
                star.x - Math.cos(star.angle) * star.length,
                star.y - Math.sin(star.angle) * star.length
            );
            gradient.addColorStop(0, `hsla(${star.hue}, 100%, 90%, ${star.opacity})`);
            gradient.addColorStop(0.1, `hsla(${star.hue + 20}, 90%, 70%, ${star.opacity * 0.8})`);
            gradient.addColorStop(0.4, `hsla(${star.hue + 40}, 80%, 50%, ${star.opacity * 0.4})`);
            gradient.addColorStop(1, 'transparent');
            
            this.ctx.beginPath();
            this.ctx.strokeStyle = gradient;
            this.ctx.lineWidth = star.thickness;
            this.ctx.lineCap = 'round';
            this.ctx.moveTo(star.x, star.y);
            this.ctx.lineTo(
                star.x - Math.cos(star.angle) * star.length,
                star.y - Math.sin(star.angle) * star.length
            );
            this.ctx.stroke();
            
            // Glowing head
            const headGlow = this.ctx.createRadialGradient(
                star.x, star.y, 0,
                star.x, star.y, star.thickness * 6
            );
            headGlow.addColorStop(0, `rgba(255, 255, 255, ${star.opacity})`);
            headGlow.addColorStop(0.3, `hsla(${star.hue}, 100%, 80%, ${star.opacity * 0.6})`);
            headGlow.addColorStop(1, 'transparent');
            
            this.ctx.beginPath();
            this.ctx.fillStyle = headGlow;
            this.ctx.arc(star.x, star.y, star.thickness * 6, 0, Math.PI * 2);
            this.ctx.fill();
            
            // Bright core
            this.ctx.beginPath();
            this.ctx.fillStyle = `rgba(255, 255, 255, ${star.opacity})`;
            this.ctx.arc(star.x, star.y, star.thickness, 0, Math.PI * 2);
            this.ctx.fill();
        });
    }

    drawNebulaClouds() {
        // Smooth mouse movement
        this.mouseX += (this.targetMouseX - this.mouseX) * 0.05;
        this.mouseY += (this.targetMouseY - this.mouseY) * 0.05;
        
        this.nebulaClouds.forEach(cloud => {
            // Orbital drift motion
            cloud.drift.angle += cloud.drift.angleSpeed;
            const orbitX = Math.cos(cloud.drift.angle) * 0.3;
            const orbitY = Math.sin(cloud.drift.angle) * 0.3;
            
            // Update cloud position with drift + mouse parallax
            cloud.x += cloud.drift.x + orbitX + (this.mouseX - 0.5) * 1.5;
            cloud.y += cloud.drift.y + orbitY + (this.mouseY - 0.5) * 1.5;
            
            // Wrap around screen with buffer
            const buffer = cloud.radius * 1.5;
            if (cloud.x < -buffer) cloud.x = this.width + buffer;
            if (cloud.x > this.width + buffer) cloud.x = -buffer;
            if (cloud.y < -buffer) cloud.y = this.height + buffer;
            if (cloud.y > this.height + buffer) cloud.y = -buffer;
            
            // Dynamic pulsating size
            const pulse = Math.sin(this.time * cloud.pulseSpeed + cloud.pulseOffset) * 0.3 + 1;
            const breathe = Math.sin(this.time * 0.002) * 0.1 + 1;
            const radius = cloud.radius * pulse * breathe;
            
            // Shifting hue over time
            const hueShift = Math.sin(this.time * 0.0015 + cloud.pulseOffset) * 30;
            const hue = cloud.hue + hueShift;
            
            // Draw multiple layers for volumetric effect
            for (let layer = 2; layer >= 0; layer--) {
                const layerRadius = radius * (1 - layer * 0.15);
                const baseOpacity = 0.012 + layer * 0.008;
                const opacity = baseOpacity * cloud.intensity;
                
                // Offset each layer slightly for 3D effect
                const layerOffsetX = Math.sin(this.time * 0.003 + layer) * 20;
                const layerOffsetY = Math.cos(this.time * 0.002 + layer) * 20;
                
                const gradient = this.ctx.createRadialGradient(
                    cloud.x + layerOffsetX, cloud.y + layerOffsetY, 0,
                    cloud.x + layerOffsetX, cloud.y + layerOffsetY, layerRadius
                );
                
                gradient.addColorStop(0, `hsla(${hue}, ${cloud.saturation}%, 45%, ${opacity * 0.5})`);
                gradient.addColorStop(0.2, `hsla(${hue + 10}, ${cloud.saturation}%, 35%, ${opacity * 0.35})`);
                gradient.addColorStop(0.5, `hsla(${hue + 20}, ${cloud.saturation - 10}%, 25%, ${opacity * 0.2})`);
                gradient.addColorStop(0.8, `hsla(${hue + 30}, ${cloud.saturation - 20}%, 15%, ${opacity * 0.08})`);
                gradient.addColorStop(1, 'transparent');
                
                this.ctx.fillStyle = gradient;
                this.ctx.beginPath();
                this.ctx.arc(cloud.x + layerOffsetX, cloud.y + layerOffsetY, layerRadius, 0, Math.PI * 2);
                this.ctx.fill();
            }
            
            // Add bright core for some clouds
            if (cloud.intensity > 0.7) {
                const coreGradient = this.ctx.createRadialGradient(
                    cloud.x, cloud.y, 0,
                    cloud.x, cloud.y, radius * 0.3
                );
                coreGradient.addColorStop(0, `hsla(${hue}, 100%, 60%, 0.025)`);
                coreGradient.addColorStop(0.5, `hsla(${hue}, 80%, 40%, 0.012)`);
                coreGradient.addColorStop(1, 'transparent');
                
                this.ctx.fillStyle = coreGradient;
                this.ctx.beginPath();
                this.ctx.arc(cloud.x, cloud.y, radius * 0.3, 0, Math.PI * 2);
                this.ctx.fill();
            }
        });
    }

    drawStars() {
        this.stars.forEach(star => {
            // Parallax effect based on mouse - deeper layers move more
            const parallax = (star.layer + 1) * 0.8;
            const offsetX = (this.mouseX - 0.5) * parallax * 30;
            const offsetY = (this.mouseY - 0.5) * parallax * 30;
            
            // Complex twinkling with multiple frequencies
            const twinkle1 = Math.sin(this.time * star.twinkleSpeed + star.twinkleOffset);
            const twinkle2 = Math.sin(this.time * star.twinkleSpeed * 2.7 + star.twinkleOffset * 1.3);
            const twinkle = (twinkle1 + twinkle2 * 0.3) / 1.3;
            const brightness = star.brightness * (0.25 + twinkle * 0.45);
            
            const x = star.x + offsetX;
            const y = star.y + offsetY;
            
            // Skip if off screen
            if (x < -20 || x > this.width + 20 || y < -20 || y > this.height + 20) return;
            
            // Larger stars get a colorful glow
            if (star.size > 1.5) {
                const glowSize = star.size * 8;
                const glow = this.ctx.createRadialGradient(x, y, 0, x, y, glowSize);
                glow.addColorStop(0, `rgba(200, 220, 255, ${brightness * 0.6})`);
                glow.addColorStop(0.2, `rgba(140, 180, 255, ${brightness * 0.25})`);
                glow.addColorStop(0.5, `rgba(100, 150, 230, ${brightness * 0.08})`);
                glow.addColorStop(1, 'transparent');
                
                this.ctx.fillStyle = glow;
                this.ctx.beginPath();
                this.ctx.arc(x, y, glowSize, 0, Math.PI * 2);
                this.ctx.fill();
                
                // Star cross/sparkle effect for bright stars
                if (brightness > 0.7) {
                    this.ctx.strokeStyle = `rgba(255, 255, 255, ${brightness * 0.3})`;
                    this.ctx.lineWidth = 1;
                    const sparkleLen = star.size * 6;
                    
                    this.ctx.beginPath();
                    this.ctx.moveTo(x - sparkleLen, y);
                    this.ctx.lineTo(x + sparkleLen, y);
                    this.ctx.moveTo(x, y - sparkleLen);
                    this.ctx.lineTo(x, y + sparkleLen);
                    this.ctx.stroke();
                }
            }
            
            // Star glow
            const gradient = this.ctx.createRadialGradient(x, y, 0, x, y, star.size * 4);
            gradient.addColorStop(0, `rgba(255, 255, 255, ${brightness})`);
            gradient.addColorStop(0.3, `rgba(220, 230, 255, ${brightness * 0.5})`);
            gradient.addColorStop(0.6, `rgba(180, 200, 255, ${brightness * 0.2})`);
            gradient.addColorStop(1, 'transparent');
            
            this.ctx.fillStyle = gradient;
            this.ctx.beginPath();
            this.ctx.arc(x, y, star.size * 4, 0, Math.PI * 2);
            this.ctx.fill();
            
            // Star core - pure white
            this.ctx.fillStyle = `rgba(255, 255, 255, ${brightness})`;
            this.ctx.beginPath();
            this.ctx.arc(x, y, star.size * 0.6, 0, Math.PI * 2);
            this.ctx.fill();
        });
    }

    drawCosmicStrands() {
        this.cosmicStrands.forEach(strand => {
            strand.wave += strand.speed;
            
            this.ctx.beginPath();
            this.ctx.strokeStyle = `hsla(${strand.hue}, 85%, 40%, 0.012)`;
            this.ctx.lineWidth = 2;
            
            const points = 20;
            for (let i = 0; i <= points; i++) {
                const t = i / points;
                const waveOffset = Math.sin(t * Math.PI * 4 + strand.wave) * 30;
                const waveOffset2 = Math.cos(t * Math.PI * 2 + strand.wave * 0.5) * 20;
                
                const x = strand.startX + Math.cos(strand.angle) * strand.length * t + 
                         Math.sin(strand.angle + Math.PI/2) * (waveOffset + waveOffset2);
                const y = strand.startY + Math.sin(strand.angle) * strand.length * t + 
                         Math.cos(strand.angle + Math.PI/2) * (waveOffset + waveOffset2);
                
                if (i === 0) {
                    this.ctx.moveTo(x, y);
                } else {
                    this.ctx.lineTo(x, y);
                }
            }
            this.ctx.stroke();
            
            // Glow layer
            this.ctx.strokeStyle = `hsla(${strand.hue}, 90%, 45%, 0.005)`;
            this.ctx.lineWidth = 8;
            this.ctx.stroke();
        });
    }

    drawParticles() {
        this.particles.forEach(particle => {
            // Update position with rotation
            particle.pulse += 0.03;
            const rotationOffset = Math.sin(particle.pulse * particle.rotationSpeed * 50) * 0.5;
            
            particle.x += particle.speedX + (this.mouseX - 0.5) * 0.5 + rotationOffset;
            particle.y += particle.speedY + (this.mouseY - 0.5) * 0.5;
            
            // Wrap around
            if (particle.x < -20) particle.x = this.width + 20;
            if (particle.x > this.width + 20) particle.x = -20;
            if (particle.y < -20) particle.y = this.height + 20;
            if (particle.y > this.height + 20) particle.y = -20;
            
            // Complex pulsing opacity
            const pulse1 = Math.sin(particle.pulse);
            const pulse2 = Math.sin(particle.pulse * 1.7 + 1);
            const opacity = particle.opacity * (0.3 + (pulse1 + pulse2 * 0.5) * 0.35);
            
            // Shifting hue
            const hue = particle.hue + Math.sin(this.time * 0.005 + particle.pulse) * 20;
            
            // Outer glow
            const outerGlow = this.ctx.createRadialGradient(
                particle.x, particle.y, 0,
                particle.x, particle.y, particle.size * 8
            );
            outerGlow.addColorStop(0, `hsla(${hue}, 95%, 50%, ${opacity * 0.35})`);
            outerGlow.addColorStop(0.3, `hsla(${hue + 10}, 85%, 38%, ${opacity * 0.15})`);
            outerGlow.addColorStop(0.6, `hsla(${hue + 20}, 75%, 28%, ${opacity * 0.05})`);
            outerGlow.addColorStop(1, 'transparent');
            
            this.ctx.fillStyle = outerGlow;
            this.ctx.beginPath();
            this.ctx.arc(particle.x, particle.y, particle.size * 8, 0, Math.PI * 2);
            this.ctx.fill();
            
            // Bright core
            this.ctx.fillStyle = `hsla(${hue}, 100%, 55%, ${opacity * 0.5})`;
            this.ctx.beginPath();
            this.ctx.arc(particle.x, particle.y, particle.size * 0.8, 0, Math.PI * 2);
            this.ctx.fill();
        });
    }

    drawAuroraWaves() {
        // Simplified aurora layers
        const auroraConfigs = [
            { hueBase: 260, yBase: 0.3, amplitude: 50, speed: 0.002 },
            { hueBase: 230, yBase: 0.65, amplitude: 60, speed: 0.0025 }
        ];
        
        auroraConfigs.forEach((config, w) => {
            this.ctx.beginPath();
            
            const hue = config.hueBase + Math.sin(this.time * 0.001 + w) * 20;
            const yOffset = this.height * config.yBase;
            
            // Larger step size for performance
            for (let x = 0; x <= this.width; x += 8) {
                const y = yOffset + 
                    Math.sin(x * 0.004 + this.time * config.speed + w) * config.amplitude;
                
                if (x === 0) {
                    this.ctx.moveTo(x, y);
                } else {
                    this.ctx.lineTo(x, y);
                }
            }
            
            // Create vertical gradient for aurora
            const gradient = this.ctx.createLinearGradient(0, yOffset - 150, 0, yOffset + 150);
            gradient.addColorStop(0, 'transparent');
            gradient.addColorStop(0.3, `hsla(${hue}, 85%, 35%, 0.012)`);
            gradient.addColorStop(0.5, `hsla(${hue + 15}, 90%, 40%, 0.02)`);
            gradient.addColorStop(0.7, `hsla(${hue}, 80%, 30%, 0.012)`);
            gradient.addColorStop(1, 'transparent');
            
            this.ctx.lineTo(this.width, this.height);
            this.ctx.lineTo(0, this.height);
            this.ctx.closePath();
            this.ctx.fillStyle = gradient;
            this.ctx.fill();
        });
    }

    drawCosmicDust() {
        // Large flowing dust clouds
        for (let i = 0; i < 4; i++) {
            const phase = this.time * 0.0003 + i * 1.2;
            const x = this.width * 0.5 + Math.sin(phase) * this.width * 0.6;
            const y = this.height * 0.5 + Math.cos(phase * 0.7) * this.height * 0.5;
            const size = 250 + Math.sin(this.time * 0.002 + i) * 100;
            const hue = 240 + i * 8 + Math.sin(this.time * 0.001) * 20;
            
            const gradient = this.ctx.createRadialGradient(x, y, 0, x, y, size);
            gradient.addColorStop(0, `hsla(${hue}, 70%, 22%, 0.012)`);
            gradient.addColorStop(0.4, `hsla(${hue + 15}, 60%, 16%, 0.007)`);
            gradient.addColorStop(0.7, `hsla(${hue + 30}, 50%, 10%, 0.003)`);
            gradient.addColorStop(1, 'transparent');
            
            this.ctx.fillStyle = gradient;
            this.ctx.beginPath();
            this.ctx.arc(x, y, size, 0, Math.PI * 2);
            this.ctx.fill();
        }
    }

    drawVortex() {
        // Subtle central vortex effect
        const cx = this.width / 2 + (this.mouseX - 0.5) * 100;
        const cy = this.height / 2 + (this.mouseY - 0.5) * 100;
        
        for (let ring = 0; ring < 3; ring++) {
            const baseRadius = 100 + ring * 80;
            const rotation = this.time * 0.001 * (ring % 2 === 0 ? 1 : -1);
            const pulseRadius = baseRadius + Math.sin(this.time * 0.003 + ring) * 30;
            
            this.ctx.beginPath();
            this.ctx.strokeStyle = `hsla(${260 + ring * 10}, 80%, 30%, 0.008)`;
            this.ctx.lineWidth = 3;
            
            for (let angle = 0; angle < Math.PI * 2; angle += 0.12) {
                const wobble = Math.sin(angle * 6 + this.time * 0.005) * 15;
                const r = pulseRadius + wobble;
                const x = cx + Math.cos(angle + rotation) * r;
                const y = cy + Math.sin(angle + rotation) * r;
                
                if (angle === 0) {
                    this.ctx.moveTo(x, y);
                } else {
                    this.ctx.lineTo(x, y);
                }
            }
            this.ctx.closePath();
            this.ctx.stroke();
        }
    }

    animate() {
        this.time++;
        
        // Smooth mouse interpolation
        this.mouseX += (this.targetMouseX - this.mouseX) * 0.05;
        this.mouseY += (this.targetMouseY - this.mouseY) * 0.05;
        
        // Clear with smooth fade
        this.ctx.fillStyle = 'rgba(3, 0, 20, 0.15)';
        this.ctx.fillRect(0, 0, this.width, this.height);
        
        // Draw all layers smoothly every frame (no frame skipping)
        this.drawCosmicDust();
        this.drawNebulaClouds();
        this.drawOrbs();
        this.drawVortex();
        this.drawCosmicStrands();
        this.drawAuroraWaves();
        this.drawStars();
        this.drawParticles();
        
        // Shooting stars
        this.spawnShootingStar();
        this.updateShootingStars();
        this.drawShootingStars();
        
        // Warp drive effect (always render when active)
        this.updateWarp();
        this.drawWarp();
        
        requestAnimationFrame(() => this.animate());
    }

    // Initialize warp stars
    initWarpStars() {
        this.warpStars = [];
        const centerX = this.width / 2;
        const centerY = this.height / 2;
        
        for (let i = 0; i < 150; i++) {
            const angle = Math.random() * Math.PI * 2;
            const distance = Math.random() * 50 + 10;
            this.warpStars.push({
                x: centerX + Math.cos(angle) * distance,
                y: centerY + Math.sin(angle) * distance,
                z: Math.random() * 1000 + 100,
                originalZ: Math.random() * 1000 + 100,
                angle: angle,
                speed: Math.random() * 15 + 8,
                size: Math.random() * 2 + 1,
                hue: Math.random() * 60 + 220,
                brightness: Math.random() * 0.5 + 0.5
            });
        }
    }

    // Start continuous warp effect (stays until stopWarp is called)
    startWarp() {
        if (this.isWarping) return;
        
        this.isWarping = true;
        this.warpProgress = 0;
        this.warpPhase = 'accelerating';
        this.continuousWarp = true;
        this.initWarpStars();
    }
    
    // Stop warp effect (triggers deceleration)
    stopWarp() {
        if (!this.isWarping) return;
        this.continuousWarp = false;
        // Force into deceleration phase
        this.warpProgress = this.warpDuration - 30;
        this.warpPhase = 'decelerating';
    }

    // Trigger warp effect (original short burst)
    triggerWarp() {
        if (this.isWarping) return;
        
        this.isWarping = true;
        this.warpProgress = 0;
        this.warpPhase = 'accelerating';
        this.continuousWarp = false;
        this.initWarpStars();
    }

    // Update warp state
    updateWarp() {
        if (!this.isWarping) return;
        
        this.warpProgress++;
        
        // Phase transitions
        if (this.warpProgress < 30) {
            this.warpPhase = 'accelerating';
        } else if (this.continuousWarp) {
            // Stay in warping phase indefinitely for continuous mode
            this.warpPhase = 'warping';
        } else if (this.warpProgress < this.warpDuration - 30) {
            this.warpPhase = 'warping';
        } else if (this.warpProgress < this.warpDuration) {
            this.warpPhase = 'decelerating';
        } else {
            this.isWarping = false;
            this.warpPhase = 'idle';
            this.warpStars = [];
            this.continuousWarp = false;
            return;
        }
        
        // Update warp star positions
        const centerX = this.width / 2;
        const centerY = this.height / 2;
        
        let speedMultiplier = 1;
        if (this.warpPhase === 'accelerating') {
            speedMultiplier = this.warpProgress / 30 * 3;
        } else if (this.warpPhase === 'warping') {
            speedMultiplier = 3;
        } else if (this.warpPhase === 'decelerating') {
            const decelProgress = (this.warpDuration - this.warpProgress) / 30;
            speedMultiplier = decelProgress * 3;
        }
        
        this.warpStars.forEach(star => {
            star.z -= star.speed * speedMultiplier;
            
            // Reset star if it passes the viewer
            if (star.z <= 0) {
                star.z = star.originalZ;
                star.angle = Math.random() * Math.PI * 2;
                const distance = Math.random() * 50 + 10;
                star.x = centerX + Math.cos(star.angle) * distance;
                star.y = centerY + Math.sin(star.angle) * distance;
            }
        });
    }

    // Draw warp effect
    drawWarp() {
        if (!this.isWarping) return;
        
        const centerX = this.width / 2;
        const centerY = this.height / 2;
        
        // Calculate intensity based on phase
        let intensity = 0;
        if (this.warpPhase === 'accelerating') {
            intensity = this.warpProgress / 30;
        } else if (this.warpPhase === 'warping') {
            intensity = 1;
        } else if (this.warpPhase === 'decelerating') {
            intensity = (this.warpDuration - this.warpProgress) / 30;
        }
        
        // Draw radial speed lines overlay
        const gradient = this.ctx.createRadialGradient(
            centerX, centerY, 0,
            centerX, centerY, Math.max(this.width, this.height) * 0.7
        );
        gradient.addColorStop(0, `rgba(150, 130, 255, ${0.15 * intensity})`);
        gradient.addColorStop(0.3, `rgba(100, 80, 200, ${0.08 * intensity})`);
        gradient.addColorStop(1, 'transparent');
        
        this.ctx.fillStyle = gradient;
        this.ctx.fillRect(0, 0, this.width, this.height);
        
        // Draw stretched warp stars as pure streaks
        this.warpStars.forEach(star => {
            const scale = 800 / star.z;
            const x2d = centerX + (star.x - centerX) * scale;
            const y2d = centerY + (star.y - centerY) * scale;
            
            // Skip if off screen
            if (x2d < -100 || x2d > this.width + 100 || y2d < -100 || y2d > this.height + 100) return;
            
            // Calculate streak length - much longer streaks
            const baseLength = (1000 - star.z) / star.z * 80 * intensity;
            const streakLength = Math.min(350, Math.max(20, baseLength));
            
            // Direction from center (streaks radiate outward)
            const dx = x2d - centerX;
            const dy = y2d - centerY;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist === 0) return;
            
            const dirX = dx / dist;
            const dirY = dy / dist;
            
            // Streak goes from current position back toward center
            const startX = x2d;
            const startY = y2d;
            const endX = x2d - dirX * streakLength;
            const endY = y2d - dirY * streakLength;
            
            // Thin, sharp streak line width
            const lineWidth = Math.max(0.5, Math.min(2.5, star.size * scale * 0.3));
            const alpha = Math.min(0.9, scale * 0.4) * star.brightness * intensity;
            
            // Create gradient for smooth streak fade
            const streakGradient = this.ctx.createLinearGradient(startX, startY, endX, endY);
            streakGradient.addColorStop(0, `hsla(${star.hue}, 70%, 75%, ${alpha * 0.9})`);
            streakGradient.addColorStop(0.15, `hsla(${star.hue + 10}, 65%, 65%, ${alpha * 0.7})`);
            streakGradient.addColorStop(0.5, `hsla(${star.hue + 20}, 55%, 55%, ${alpha * 0.3})`);
            streakGradient.addColorStop(1, 'transparent');
            
            // Draw the streak line
            this.ctx.beginPath();
            this.ctx.strokeStyle = streakGradient;
            this.ctx.lineWidth = lineWidth;
            this.ctx.lineCap = 'round';
            this.ctx.moveTo(startX, startY);
            this.ctx.lineTo(endX, endY);
            this.ctx.stroke();
            
            // Add subtle glow line behind for depth (wider, more transparent)
            if (streakLength > 50) {
                const glowGradient = this.ctx.createLinearGradient(startX, startY, endX, endY);
                glowGradient.addColorStop(0, `hsla(${star.hue}, 80%, 70%, ${alpha * 0.2})`);
                glowGradient.addColorStop(0.4, `hsla(${star.hue + 15}, 70%, 55%, ${alpha * 0.1})`);
                glowGradient.addColorStop(1, 'transparent');
                
                this.ctx.beginPath();
                this.ctx.strokeStyle = glowGradient;
                this.ctx.lineWidth = lineWidth * 3;
                this.ctx.lineCap = 'round';
                this.ctx.moveTo(startX, startY);
                this.ctx.lineTo(endX, endY);
                this.ctx.stroke();
            }
        });
        
        // Central flash during peak warp
        if (this.warpPhase === 'warping') {
            const flash = this.ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, 150);
            flash.addColorStop(0, `rgba(200, 180, 255, ${0.15 * Math.sin(this.warpProgress * 0.2)})`);
            flash.addColorStop(1, 'transparent');
            this.ctx.fillStyle = flash;
            this.ctx.beginPath();
            this.ctx.arc(centerX, centerY, 150, 0, Math.PI * 2);
            this.ctx.fill();
        }
    }
}

// Global nebula instance
let nebulaInstance = null;

// Global function to trigger warp effect (short burst)
window.triggerWarpEffect = function() {
    if (nebulaInstance) {
        nebulaInstance.triggerWarp();
    }
};

// Global function to start continuous warp effect
window.startWarpEffect = function() {
    if (nebulaInstance) {
        nebulaInstance.startWarp();
    }
};

// Global function to stop continuous warp effect
window.stopWarpEffect = function() {
    if (nebulaInstance) {
        nebulaInstance.stopWarp();
    }
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    nebulaInstance = new NebulaBackground();
});
