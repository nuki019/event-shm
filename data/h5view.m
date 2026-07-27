function varargout = h5view(filename,filepath)
% Visualize structure of a h5-container
% INPUT
%   filename (string), e.g. 'pc_f80kHz.h5'
%   filepath (string) *optional* (If h5-file is not in current folder)
% OUTPUT *optional*
%   structure-file, containing information about the HDF5 file (according
%   to inbuild h5info.
% 

clear h5nodes
clear h5nodeNames
clear h5nodeType

switch nargin
    case 2 
        file = fullfile(filepath,filename);
    case 1
        file = fullfile(pwd,filename);
    otherwise
        error('h5view:nbrInputArgs','Unexpected number of input arguments.')
end

h = h5info(file);
varargout{1} = h;

% Initialize root
h5nodes(1) = 0;
try
    tmp = cell2mat(h.Name);
end
if exist('tmp','var') && ~isempty(tmp)
    h5nodeNames{1} = tmp;
else
    h5nodeNames{1} = filename;
end
h5nodeType{1} = 'G';
parentNode = length(h5nodeNames);

% Look for data in root
[h5nodes,h5nodeNames,h5nodeType] = getData(h,parentNode,h5nodes,h5nodeNames,h5nodeType);

% Look for folders (recursively!)
[h5nodes,h5nodeNames,h5nodeType] = getFolder(h,parentNode,h5nodes,h5nodeNames,h5nodeType);

% Visualize h5-container
figure('Name','H5view','NumberTitle','off')
    % Plot tree
    treeplot(h5nodes)
    % Name tree
    [x,y] = treelayout(h5nodes);
    for ii=2:length(x) % Do not name root
        if h5nodeType{ii} == 'G' % make folders bold
            text(x(ii),y(ii),h5nodeNames{ii},'FontWeight','bold','HorizontalAlignment','center','Interpreter','none')
        else
            text(x(ii),y(ii),h5nodeNames{ii},'HorizontalAlignment','center','Interpreter','none')
        end
    end
    % Make plot nice
    title(filename,'Interpreter','none')
    set(gca,'xticklabel',[])
    set(gca,'yticklabel',[])
    set(gca,'xtick',[])
    set(gca,'ytick',[])

end

function [h5nodes,h5nodeNames,h5nodeType] = getData(parentStruc,parentNode,h5nodes,h5nodeNames,h5nodeType)
if ~isempty(parentStruc.Datasets)
    for ii = 1:size(parentStruc.Datasets,1)
        h5nodes = horzcat(h5nodes,parentNode);
        h5nodeNames{end+1} = parentStruc.Datasets(ii).Name;
        h5nodeType{end+1} = 'D';
    end
end
end

function [h5nodes,h5nodeNames,h5nodeType] = getFolder(parentStruc,parentNode,h5nodes,h5nodeNames,h5nodeType)
if ~isempty(parentStruc.Groups)
    for ii = 1:size(parentStruc.Groups,1)
        h5nodes = horzcat(h5nodes,parentNode);
        h5nodeNames{end+1} = parentStruc.Groups(ii).Name;
        h5nodeType{end+1} = 'G';
        [h5nodes,h5nodeNames,h5nodeType] = getData(parentStruc.Groups(ii),(length(h5nodeNames)),h5nodes,h5nodeNames,h5nodeType);
        [h5nodes,h5nodeNames,h5nodeType] = getFolder(parentStruc.Groups(ii),(length(h5nodeNames)),h5nodes,h5nodeNames,h5nodeType);
    end
end
end