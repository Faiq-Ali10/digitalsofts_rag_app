# Use official Node.js Alpine image for a smaller footprint
FROM node:20-alpine

# Set working directory
WORKDIR /app

# Install dependencies (only package.json and package-lock.json first for cache)
COPY package.json package-lock.json* ./
RUN npm ci

# Copy all files
COPY . .

# Expose port
EXPOSE 3000

# Start in development mode
CMD ["npm", "run", "dev"]
