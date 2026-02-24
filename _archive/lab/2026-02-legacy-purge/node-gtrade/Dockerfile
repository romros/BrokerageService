FROM node:20-slim

WORKDIR /app

# Install Python3 (for bridge demo)
RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*

# Copy package files
COPY package.json ./

# Install dependencies
RUN npm install

# Copy source
COPY *.js ./

# Default command
CMD ["node", "simpleQuote.js"]
