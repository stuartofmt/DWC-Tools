# Download and install nvm:
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.6/install.sh | bash

# in lieu of restarting the shell
\. "$HOME/.nvm/nvm.sh"

# Download and install Node.js:
nvm install 24

echo "Node.js version:"
node -v # Should print "v24.18.1".

echo  "npm version:"
npm -v # Should print "11.16.0".
