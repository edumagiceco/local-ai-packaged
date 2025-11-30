# Build n8n from edumagiceco/n8n repository
FROM node:20-alpine AS builder

# Install build dependencies
RUN apk add --no-cache git python3 make g++ py3-setuptools

# Clone the edumagiceco/n8n repository
WORKDIR /build
RUN git clone --depth 1 https://github.com/edumagiceco/n8n.git .

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Install dependencies and build (with retry for network issues)
RUN pnpm install || pnpm install || pnpm install
RUN pnpm build

# Production image
FROM node:20-alpine

# Install runtime dependencies
RUN apk add --no-cache \
    tini \
    tzdata \
    su-exec

# Create n8n user
RUN addgroup -S n8n && adduser -S n8n -G n8n

# Set working directory
WORKDIR /home/node

# Copy built files from builder
COPY --from=builder /build /home/node/n8n

# Set ownership
RUN chown -R n8n:n8n /home/node

# Install pnpm in production image
RUN corepack enable && corepack prepare pnpm@latest --activate

# Set environment variables
ENV NODE_ENV=production
ENV N8N_USER_FOLDER=/home/node/.n8n

# Create data directory
RUN mkdir -p /home/node/.n8n && chown -R n8n:n8n /home/node/.n8n

# Expose port
EXPOSE 5678

# Set user
USER n8n

WORKDIR /home/node/n8n

# Start n8n
ENTRYPOINT ["tini", "--"]
CMD ["pnpm", "start"]
