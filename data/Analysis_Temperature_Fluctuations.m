clear all
clc
close all

% Define frequency vector
frequency = 40:20:260; %kHz

% Read temperature values from h5-files; 
% 90 folders with 12 frequencies lead to 1080 temperature measurements
% for the top and bottom temperature sensor
foldername = 'Data';
D = dir(foldername);
coll_temperatures = [];
for jj = 1 : length(frequency)
    freq_act = frequency(jj);
    for ii = 3 : size(D,1)        
        filename = D(ii).name;
        temperatures = h5read(['Data/' filename '/pc_f' num2str(freq_act) 'kHz.h5'],'/Temperature/values');
        coll_temperatures = [coll_temperatures temperatures];
    end
end

% Visualization
linewidth = 1.3;
set(gcf,'Position',[100 100 600 400],'Color','w')
set(gcf,'PaperPositionMode','auto');
hold on
box on
h1=plot(coll_temperatures(1,:),'b','LineWidth',linewidth);
h2=plot(coll_temperatures(2,:),'r','LineWidth',linewidth);
legend([h1(1); h2],'Temperature sensor (bottom)','Temperature sensor (top)')
axis tight
xlabel('Measurements (one per h5-file)')
ylabel('Temperature (°C)')
