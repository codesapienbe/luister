// Particle System
class ParticleSystem {
    constructor() {
        this.canvas = document.createElement('canvas');
        this.ctx = this.canvas.getContext('2d');
        this.particles = [];
        this.particleCount = 50;
        
        this.setupCanvas();
        this.createParticles();
        this.animate();
        
        window.addEventListener('resize', () => this.setupCanvas());
    }
    
    setupCanvas() {
        const container = document.getElementById('particles');
        container.appendChild(this.canvas);
        
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
        this.canvas.style.position = 'fixed';
        this.canvas.style.top = '0';
        this.canvas.style.left = '0';
        this.canvas.style.pointerEvents = 'none';
        this.canvas.style.zIndex = '1';
    }
    
    createParticles() {
        this.particles = [];
        for (let i = 0; i < this.particleCount; i++) {
            this.particles.push({
                x: Math.random() * this.canvas.width,
                y: Math.random() * this.canvas.height,
                size: Math.random() * 3 + 1,
                speedX: (Math.random() - 0.5) * 0.5,
                speedY: (Math.random() - 0.5) * 0.5,
                opacity: Math.random() * 0.5 + 0.2,
                color: Math.random() > 0.5 ? '#00d4ff' : '#ff006e'
            });
        }
    }
    
    animate() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        this.particles.forEach(particle => {
            particle.x += particle.speedX;
            particle.y += particle.speedY;
            
            // Wrap around screen
            if (particle.x < 0) particle.x = this.canvas.width;
            if (particle.x > this.canvas.width) particle.x = 0;
            if (particle.y < 0) particle.y = this.canvas.height;
            if (particle.y > this.canvas.height) particle.y = 0;
            
            // Draw particle
            this.ctx.beginPath();
            this.ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            this.ctx.fillStyle = particle.color;
            this.ctx.globalAlpha = particle.opacity;
            this.ctx.fill();
        });
        
        requestAnimationFrame(() => this.animate());
    }
}

// Typewriter Effect
class TypeWriter {
    constructor(element, text, speed = 100) {
        this.element = element;
        this.text = text;
        this.speed = speed;
        this.index = 0;
        this.isTyping = false;
    }
    
    type() {
        if (this.isTyping) return;
        
        this.isTyping = true;
        this.element.textContent = '';
        
        const typeInterval = setInterval(() => {
            if (this.index < this.text.length) {
                this.element.textContent += this.text.charAt(this.index);
                this.index++;
            } else {
                clearInterval(typeInterval);
                this.isTyping = false;
                this.index = 0;
            }
        }, this.speed);
    }
    
    start() {
        this.type();
        // Restart typing every 5 seconds
        setInterval(() => {
            if (!this.isTyping) {
                this.type();
            }
        }, 5000);
    }
}

// Smooth Scrolling
function smoothScroll(target) {
    const element = document.querySelector(target);
    if (element) {
        element.scrollIntoView({
            behavior: 'smooth',
            block: 'start'
        });
    }
}

// Copy to Clipboard
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        const copyBtn = document.getElementById('copyBtn');
        const originalText = copyBtn.querySelector('.copy-text').textContent;
        
        copyBtn.querySelector('.copy-text').textContent = 'Copied!';
        copyBtn.style.background = '#00ff88';
        
        setTimeout(() => {
            copyBtn.querySelector('.copy-text').textContent = originalText;
            copyBtn.style.background = '#00d4ff';
        }, 2000);
    });
}

// Intersection Observer for Animations
class AnimationObserver {
    constructor() {
        this.observer = new IntersectionObserver(
            (entries) => this.handleIntersection(entries),
            { threshold: 0.1, rootMargin: '50px' }
        );
        
        this.setupObserver();
    }
    
    setupObserver() {
        // Observe feature cards
        document.querySelectorAll('.feature-card').forEach(card => {
            this.observer.observe(card);
        });
        
        // Observe roadmap items
        document.querySelectorAll('.roadmap__item').forEach(item => {
            this.observer.observe(item);
        });
        
        // Observe progress bars
        document.querySelectorAll('.progress-fill').forEach(bar => {
            this.observer.observe(bar);
        });
    }
    
    handleIntersection(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const element = entry.target;
                
                // Animate feature cards
                if (element.classList.contains('feature-card')) {
                    element.style.transform = 'translateY(0)';
                    element.style.opacity = '1';
                }
                
                // Animate roadmap items
                if (element.classList.contains('roadmap__item')) {
                    element.style.transform = 'translateX(0)';
                    element.style.opacity = '1';
                }
                
                // Animate progress bars
                if (element.classList.contains('progress-fill')) {
                    const progress = element.getAttribute('data-progress');
                    element.style.width = progress + '%';
                }
            }
        });
    }
}

// Header Scroll Effect
class HeaderScroll {
    constructor() {
        this.header = document.querySelector('.header');
        this.lastScrollY = 0;
        
        window.addEventListener('scroll', () => this.handleScroll());
    }
    
    handleScroll() {
        const scrollY = window.scrollY;
        
        if (scrollY > 100) {
            this.header.style.background = 'rgba(10, 10, 15, 0.98)';
            this.header.style.boxShadow = '0 2px 20px rgba(0, 0, 0, 0.3)';
        } else {
            this.header.style.background = 'rgba(10, 10, 15, 0.95)';
            this.header.style.boxShadow = 'none';
        }
        
        this.lastScrollY = scrollY;
    }
}

// Counter Animation
class CounterAnimation {
    constructor() {
        this.counters = document.querySelectorAll('.stat__number');
        this.setupCounters();
    }
    
    setupCounters() {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    this.animateCounter(entry.target);
                }
            });
        }, { threshold: 0.5 });
        
        this.counters.forEach(counter => {
            observer.observe(counter);
        });
    }
    
    animateCounter(element) {
        const target = element.textContent;
        if (target === '∞' || target === '100%') return;
        
        const targetNumber = parseInt(target);
        let current = 0;
        const increment = targetNumber / 30;
        
        const updateCounter = () => {
            if (current < targetNumber) {
                current += increment;
                element.textContent = Math.floor(current);
                requestAnimationFrame(updateCounter);
            } else {
                element.textContent = target;
            }
        };
        
        updateCounter();
    }
}

// Equalizer Animation
class EqualizerAnimation {
    constructor() {
        this.bars = document.querySelectorAll('.equalizer .bar');
        this.isAnimating = false;
        this.setupAnimation();
    }
    
    setupAnimation() {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting && !this.isAnimating) {
                    this.startAnimation();
                }
            });
        }, { threshold: 0.5 });
        
        const equalizer = document.querySelector('.equalizer');
        if (equalizer) {
            observer.observe(equalizer);
        }
    }
    
    startAnimation() {
        this.isAnimating = true;
        
        this.bars.forEach((bar, index) => {
            const animate = () => {
                const height = Math.random() * 50 + 20;
                bar.style.height = height + 'px';
                
                setTimeout(() => {
                    if (this.isAnimating) {
                        animate();
                    }
                }, Math.random() * 500 + 300);
            };
            
            setTimeout(animate, index * 100);
        });
    }
}

// Button Ripple Effect
class RippleEffect {
    constructor() {
        this.setupRippleEffect();
    }
    
    setupRippleEffect() {
        document.querySelectorAll('.btn').forEach(button => {
            button.addEventListener('click', (e) => {
                const ripple = document.createElement('span');
                const rect = button.getBoundingClientRect();
                const size = Math.max(rect.width, rect.height);
                const x = e.clientX - rect.left - size / 2;
                const y = e.clientY - rect.top - size / 2;
                
                ripple.style.width = ripple.style.height = size + 'px';
                ripple.style.left = x + 'px';
                ripple.style.top = y + 'px';
                ripple.classList.add('ripple');
                
                button.appendChild(ripple);
                
                setTimeout(() => {
                    ripple.remove();
                }, 600);
            });
        });
    }
}

// Navigation Smooth Scrolling
function setupNavigation() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
}

// Initialize everything when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Initialize particle system
    new ParticleSystem();
    
    // Initialize typewriter effect
    const typewriterElement = document.getElementById('typewriter');
    if (typewriterElement) {
        const typewriter = new TypeWriter(typewriterElement, 'uvx run --from https://github.com/codesapienbe/luister/releases/download/v2025.07.06.1321/luister-0.1.0-py3-none-any.whl', 150);
        setTimeout(() => {
            typewriter.start();
        }, 1000);
    }
    
    // Setup copy button
    const copyBtn = document.getElementById('copyBtn');
    if (copyBtn) {
        copyBtn.addEventListener('click', () => {
            copyToClipboard('uvx run --from https://github.com/codesapienbe/luister/releases/download/v2025.07.06.1321/luister-0.1.0-py3-none-any.whl');
        });
    }
    
    // Initialize animations
    new AnimationObserver();
    new HeaderScroll();
    new CounterAnimation();
    new EqualizerAnimation();
    new RippleEffect();
    
    // Setup smooth scrolling navigation
    setupNavigation();
    
    // Initial animations for elements
    const initialAnimations = () => {
        // Feature cards initial state
        document.querySelectorAll('.feature-card').forEach((card, index) => {
            card.style.transform = 'translateY(50px)';
            card.style.opacity = '0';
            card.style.transition = 'all 0.6s ease';
            card.style.transitionDelay = (index * 0.1) + 's';
        });
        
        // Roadmap items initial state
        document.querySelectorAll('.roadmap__item').forEach((item, index) => {
            item.style.transform = 'translateX(-50px)';
            item.style.opacity = '0';
            item.style.transition = 'all 0.6s ease';
            item.style.transitionDelay = (index * 0.2) + 's';
        });
        
        // Progress bars initial state
        document.querySelectorAll('.progress-fill').forEach(bar => {
            bar.style.width = '0%';
            bar.style.transition = 'width 2s ease';
        });
    };
    
    initialAnimations();
});

// Add CSS for ripple effect
const style = document.createElement('style');
style.textContent = `
    .btn {
        position: relative;
        overflow: hidden;
    }
    
    .ripple {
        position: absolute;
        border-radius: 50%;
        background: rgba(255, 255, 255, 0.3);
        transform: scale(0);
        animation: ripple-animation 0.6s ease-out;
        pointer-events: none;
    }
    
    @keyframes ripple-animation {
        to {
            transform: scale(2);
            opacity: 0;
        }
    }
    
    .hero__visual {
        transform: translateY(0);
        opacity: 1;
        animation: fadeInUp 1s ease-out 0.5s both;
    }
    
    @keyframes fadeInUp {
        from {
            transform: translateY(30px);
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }
    
    .hero__text {
        animation: fadeInLeft 1s ease-out both;
    }
    
    @keyframes fadeInLeft {
        from {
            transform: translateX(-30px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
`;
document.head.appendChild(style);

// Preload optimization
window.addEventListener('load', () => {
    // Remove any loading states
    document.body.classList.add('loaded');
    
    // Start more intensive animations after load
    setTimeout(() => {
        document.querySelectorAll('.feature-card').forEach(card => {
            card.addEventListener('mouseenter', () => {
                card.style.transform = 'translateY(-12px) scale(1.02)';
            });
            
            card.addEventListener('mouseleave', () => {
                card.style.transform = 'translateY(0) scale(1)';
            });
        });
    }, 500);
});