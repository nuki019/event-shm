clear all
clc
close all

% Frequency
frequency = 60; %kHz

% Transducer pairs (ID)
channel_1 = 6;
channel_2 = 51;

% Damage case
damage_case = 'D1';

% Read signals
foldername = 'Data';
D = dir(foldername);
coll_catch_ch1 = [];
coll_catch_ch2 = [];
for ii = 3 : size(D,1) - 2
    
    % Current filename
    filename = D(ii).name;
    
    % Read baseline measurements
    if ~isempty(intersect(filename,'baseline'))
        transducer_pairs = h5read(['Data/' filename '/pc_f' num2str(frequency) 'kHz.h5'],'/command/pitchcatch/channels');
        transducer_pairs = transducer_pairs + 1;
        data_all = h5read(['Data/' filename '/pc_f' num2str(frequency) 'kHz.h5'],'/pitchcatch/catch');
        coll_catch_ch1 = [coll_catch_ch1 data_all(:,channel_1)];
        coll_catch_ch2 = [coll_catch_ch2 data_all(:,channel_2)];
    end
    
    % Read measurement from damage structure
    idx = find(filename == 'D');
    try
        if strcmp(filename(idx:end),damage_case) 
            data_all = h5read(['Data/' filename '/pc_f' num2str(frequency) 'kHz.h5'],'/pitchcatch/catch');
        
            signal_damaged_ch1 = data_all(:,channel_1);
            signal_damaged_ch2 = data_all(:,channel_2);
        end
    catch
       
    end
end

% High-pass filtering
f_u = 20e3;
fs = 10e6; dt = 1/fs;
filt_ord = 3;
f_nyquist = fs/2;
Wn = f_u / f_nyquist;
[B,A] = butter(filt_ord,Wn,'high');
coll_catch_ch1 = filtfilt(B,A,coll_catch_ch1);
coll_catch_ch2 = filtfilt(B,A,coll_catch_ch2);
signal_damaged_ch1 = filtfilt(B,A,signal_damaged_ch1);
signal_damaged_ch2 = filtfilt(B,A,signal_damaged_ch2);

time = 0 : dt : dt*(size(coll_catch_ch1,1)-1);
time = time * 1e6;

% Visualization
start_idx = 1;
end_idx = 7000;

linewidth = 1.3;
figure
set(gcf,'Position',[100 100 600 600],'Color','w')
set(gcf,'PaperPositionMode','auto');
subplot(3,1,1)
hold on
box on
title(['Transducer pairs: ' num2str(transducer_pairs(:,channel_1)')])
h1=plot(time(start_idx:end_idx),coll_catch_ch1(start_idx:end_idx,:),'b','LineWidth',linewidth);
h2=plot(time(start_idx:end_idx),signal_damaged_ch1(start_idx:end_idx,:),'r','LineWidth',linewidth);
legend([h1(1); h2],'baselines (60x)',damage_case)
ylim([-0.15 0.15])
ylabel('Amplitude (V)')

subplot(3,1,2)
hold on
box on
title(['Transducer pairs: ' num2str(transducer_pairs(:,channel_2)')])
h1=plot(time(start_idx:end_idx),coll_catch_ch2(start_idx:end_idx,:),'b','LineWidth',linewidth);
h2=plot(time(start_idx:end_idx),signal_damaged_ch2(start_idx:end_idx,:),'r','LineWidth',linewidth);
legend([h1(1); h2],'baselines (60x)',damage_case)
ylim([-0.15 0.15])
ylabel('Amplitude (V)')

subplot(3,1,3)
hold on
box on
title(['Differential signal: ' 'Transducer pairs: ' num2str(transducer_pairs(:,channel_2)')])
h1=plot(time(start_idx:end_idx),coll_catch_ch2(start_idx:end_idx,2:end) - repmat(coll_catch_ch2(start_idx:end_idx,1),1,59),'b','LineWidth',linewidth);
h2=plot(time(start_idx:end_idx),coll_catch_ch2(start_idx:end_idx,2) - signal_damaged_ch2(start_idx:end_idx,:),'r','LineWidth',linewidth);
legend([h1(1); h2],'intact (59x)',damage_case)
xlabel('Time (µs)')
ylabel('Amplitude (V)')